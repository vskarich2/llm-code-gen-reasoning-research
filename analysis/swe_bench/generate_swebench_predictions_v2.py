"""Generate gpt-5.4-mini predictions for SWE-bench tasks.

For each task: clone repo, checkout base commit, read oracle files,
send problem statement + source code to model, extract patch.
"""

import json, subprocess, tempfile, os, re, time, shutil
from pathlib import Path
from openai import OpenAI

TASKS = json.load(open("analysis/swebench_task_list.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
OUT_PATH = "analysis/swebench_predictions.jsonl"

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


def clone_and_read(repo, base_commit, oracle_files):
    """Clone repo at base_commit, read oracle files, return contents."""
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
    """Format source files for the prompt."""
    parts = []
    for path, content in file_contents.items():
        parts.append(f"### {path}\n```python\n{content}\n```")
    return "\n\n".join(parts)


def extract_changed_files(patch_text):
    """Extract file paths from unified diff or model format."""
    files = set()
    for line in patch_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) >= 2:
                files.add(parts[-1])
        elif line.startswith("+++ b/"):
            files.add(line[6:])
        elif line.startswith("--- a/"):
            f = line[6:]
            if f != "/dev/null":
                files.add(f)
        elif line.startswith("*** Update File:"):
            f = line.split("*** Update File:")[-1].strip()
            if f: files.add(f)
    files.discard("/dev/null")
    files.discard("dev/null")
    return sorted(files)


def generate_one(task_row, oracle_files):
    """Generate prediction for one task."""
    file_contents = clone_and_read(task_row["repo"], task_row["base_commit"], oracle_files)

    if not file_contents:
        return {"patch": "", "changed_files": [], "reasoning": "ERROR: could not read source files"}

    source_text = format_source_files(file_contents)
    prompt = PROMPT.format(
        repo=task_row["repo"],
        problem_statement=task_row["problem_statement"],
        source_files=source_text,
    )

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_completion_tokens=4096,
    )

    raw = response.choices[0].message.content

    patch = raw
    if "```" in raw:
        blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", raw, re.DOTALL)
        if blocks:
            patch = blocks[0]

    changed_files = extract_changed_files(patch)

    return {"patch": patch.strip(), "changed_files": changed_files, "reasoning": raw[:500]}


def main():
    # Load task instances
    HF_TOKEN = os.environ.get("HF_TOKEN", "")
    os.environ["HF_TOKEN"] = HF_TOKEN

    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    ds_map = {row["instance_id"]: row for row in ds}

    with open(OUT_PATH, "w") as f:
        for i, iid in enumerate(TASKS):
            print(f"[{i+1}/{len(TASKS)}] {iid}...", end=" ", flush=True)

            row = ds_map[iid]
            oracle_files = REF_FILES[iid]

            try:
                result = generate_one(row, oracle_files)
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model": "gpt-5.4-mini",
                    "model_patch": result["patch"],
                    "patch": result["patch"],
                    "changed_files": result["changed_files"],
                    "reasoning": result["reasoning"],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
                n = len(result["changed_files"])
                print(f"OK ({n} files: {result['changed_files'][:3]})")
            except Exception as e:
                print(f"ERROR: {e}")
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model": "gpt-5.4-mini",
                    "model_patch": "",
                    "patch": "",
                    "changed_files": [],
                    "reasoning": f"ERROR: {e}",
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()

            time.sleep(0.5)

    print(f"\nDone. {len(TASKS)} predictions saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
