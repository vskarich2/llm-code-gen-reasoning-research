import json, subprocess, tempfile, os, re, time, shutil
from pathlib import Path
from openai import OpenAI

TASKS = json.load(open("analysis/swebench_task_list.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

PROMPT = """You are a software engineer fixing a bug in an open-source Python project.

Repository: {repo}

## Problem Description

{problem_statement}

## Source Files

{source_files}

## Instructions

Produce a unified diff patch that fixes this bug. The patch should be applicable with `git apply`.

Rules:
- Output ONLY the unified diff patch
- Use the standard format: diff --git a/path b/path
- Include file paths relative to the repo root
- Do not include test file changes
- Fix the root cause, not symptoms

Output your patch now:"""

RETRY_PROMPT = """Your previous fix did not fully address the problem. Consider this feedback:

{hint}

Try again. Produce a unified diff patch.

Rules:
- Output ONLY the unified diff patch
- Use the standard format: diff --git a/path b/path
- Fix the root cause, not symptoms

Output your patch now:"""

HINTS = {
    "trace_value": "Trace the value from where it is first created to where it is consumed; identify the first point where its representation becomes incorrect.",
    "first_corruption": "The fix belongs at the first point where the value is modified incorrectly, not at any downstream consumer.",
    "fix_not_consumer": "If a value is transformed incorrectly at any point in the pipeline, fix that transformation rather than patching the consumer.",
    "multi_file": "This bug likely requires changes in multiple files. Check if your fix needs to be propagated to other files that interact with the one you changed.",
}


def clone_and_read(repo, base_commit, oracle_files):
    tmpdir = tempfile.mkdtemp(prefix="swe_")
    try:
        repo_url = f"https://github.com/{repo}.git"
        repo_dir = tmpdir + "/repo"
        subprocess.run(["git", "clone", "--depth", "1", repo_url, repo_dir],
                       capture_output=True, timeout=120)
        subprocess.run(["git", "fetch", "--depth", "1", "origin", base_commit],
                       capture_output=True, cwd=repo_dir, timeout=60)
        subprocess.run(["git", "checkout", base_commit],
                       capture_output=True, cwd=repo_dir, timeout=30)
        file_contents = {}
        for f in oracle_files:
            fpath = Path(repo_dir) / f
            if fpath.exists():
                file_contents[f] = fpath.read_text(errors="replace")
        return file_contents
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def format_source_files(file_contents):
    parts = []
    for path, content in file_contents.items():
        parts.append(f"### {path}\n```python\n{content}\n```")
    return "\n\n".join(parts)


def extract_changed_files(patch_text):
    files = set()
    for line in patch_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) >= 2: files.add(parts[-1])
        elif line.startswith("+++ b/"): files.add(line[6:])
        elif line.startswith("--- a/"):
            f = line[6:]
            if f != "/dev/null": files.add(f)
        elif line.startswith("*** Update File:"):
            f = line.split("*** Update File:")[-1].strip()
            if f: files.add(f)
    files.discard("/dev/null")
    files.discard("dev/null")
    return sorted(files)


def call_model(messages):
    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=messages,
        temperature=0.0,
        max_completion_tokens=4096,
    )
    raw = response.choices[0].message.content
    patch = raw
    if "```" in raw:
        blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", raw, re.DOTALL)
        if blocks: patch = blocks[0]
    return patch.strip(), raw[:500]


def run_one(task_row, oracle_files, hint_name, hint_text):
    file_contents = clone_and_read(task_row["repo"], task_row["base_commit"], oracle_files)
    if not file_contents:
        return {"patch": "", "changed_files": [], "a0_patch": "", "a0_changed": [], "hint_used": False}

    source_text = format_source_files(file_contents)
    prompt = PROMPT.format(
        repo=task_row["repo"],
        problem_statement=task_row["problem_statement"],
        source_files=source_text,
    )

    # Attempt 0: no hint
    messages = [{"role": "user", "content": prompt}]
    a0_patch, a0_raw = call_model(messages)
    a0_changed = extract_changed_files(a0_patch)

    # Check if a0 covers all reference files
    ref = set(oracle_files)
    a0_covers_all = ref.issubset(set(a0_changed))

    if a0_covers_all:
        return {
            "patch": a0_patch, "changed_files": a0_changed,
            "a0_patch": a0_patch, "a0_changed": a0_changed,
            "hint_used": False, "reasoning": a0_raw,
        }

    # Attempt 1: with hint
    retry = RETRY_PROMPT.format(hint=hint_text)
    messages.append({"role": "assistant", "content": a0_raw})
    messages.append({"role": "user", "content": retry})
    a1_patch, a1_raw = call_model(messages)
    a1_changed = extract_changed_files(a1_patch)

    return {
        "patch": a1_patch, "changed_files": a1_changed,
        "a0_patch": a0_patch, "a0_changed": a0_changed,
        "hint_used": True, "reasoning": a1_raw,
    }


def main():
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    ds_map = {row["instance_id"]: row for row in ds}

    for hint_name, hint_text in HINTS.items():
        out_path = f"analysis/swebench_hint_{hint_name}.jsonl"
        print(f"\n{'='*60}")
        print(f"HINT: {hint_name}")
        print(f"{'='*60}")

        with open(out_path, "w") as f:
            for i, iid in enumerate(TASKS):
                print(f"  [{i+1}/{len(TASKS)}] {iid}...", end=" ", flush=True)
                row = ds_map[iid]
                oracle_files = REF_FILES[iid]
                try:
                    result = run_one(row, oracle_files, hint_name, hint_text)
                    pred = {
                        "instance_id": iid,
                        "hint": hint_name,
                        "changed_files": result["changed_files"],
                        "a0_changed": result["a0_changed"],
                        "hint_used": result["hint_used"],
                        "a0_covers_all": set(oracle_files).issubset(set(result["a0_changed"])),
                        "a1_covers_all": set(oracle_files).issubset(set(result["changed_files"])),
                    }
                    f.write(json.dumps(pred) + "\n")
                    f.flush()
                    status = "hint_used" if result["hint_used"] else "a0_ok"
                    a1_all = "ALL" if pred["a1_covers_all"] else f"{len(set(result['changed_files']) & set(oracle_files))}/{len(oracle_files)}"
                    print(f"{status} files={result['changed_files'][:3]} coverage={a1_all}")
                except Exception as e:
                    print(f"ERROR: {e}")
                    f.write(json.dumps({"instance_id": iid, "hint": hint_name, "error": str(e)}) + "\n")
                time.sleep(0.5)

    print("\nDone.")


if __name__ == "__main__":
    main()
