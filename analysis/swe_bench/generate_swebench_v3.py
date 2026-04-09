"""Generate predictions using SWE-bench's exact prompt format.

Uses style-3 prompt with oracle files, produces patches that git apply can handle.
"""

import json, subprocess, tempfile, os, re, time, shutil
from pathlib import Path
from openai import OpenAI

TASKS = json.load(open("analysis/swebench_task_list.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
OUT_PATH = "analysis/swebench_predictions_v3.jsonl"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

PATCH_EXAMPLE = """--- a/file.py
+++ b/file.py
@@ -1,27 +1,35 @@
 def euclidean(a, b):
-    while b:
-        a, b = b, a % b
-    return a
+    if b == 0:
+        return a
+    return euclidean(b, a % b)"""

PROMPT = """You will be provided with a partial code base and an issue statement explaining a problem to resolve.

<issue>
{problem_statement}
</issue>

<code>
{code_text}
</code>

Here is an example of a patch file. It consists of changes to the code base. It specifies the file names, the line numbers of each change, and the removed and added lines. A single patch file can contain changes to multiple files.

<patch>
{patch_example}
</patch>

I need you to solve the provided issue by generating a single patch file that I can apply directly to this repository using git apply. Please respond with a single patch file in the format shown above.
Respond below:
"""


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


def make_code_text(file_contents):
    parts = []
    for path, content in file_contents.items():
        parts.append(f"[start of {path}]")
        parts.append(content)
        parts.append(f"[end of {path}]")
    return "\n".join(parts)


def extract_patch(raw_response):
    """Extract patch from response, handling various formats."""
    # Try to find content between <patch> tags
    match = re.search(r"<patch>(.*?)</patch>", raw_response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try markdown code blocks
    blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", raw_response, re.DOTALL)
    if blocks:
        return blocks[0].strip()

    # If response starts with --- or diff, it's the patch itself
    lines = raw_response.strip().split("\n")
    patch_lines = []
    in_patch = False
    for line in lines:
        if line.startswith("---") or line.startswith("diff --git"):
            in_patch = True
        if in_patch:
            patch_lines.append(line)

    if patch_lines:
        return "\n".join(patch_lines)

    return raw_response.strip()


def extract_changed_files(patch_text):
    files = set()
    for line in patch_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) >= 2: files.add(parts[-1])
        elif line.startswith("+++ b/"):
            files.add(line[6:])
        elif line.startswith("+++ ") and not line.startswith("+++ b/"):
            f = line[4:].strip()
            if f and "/" in f: files.add(f)
        elif line.startswith("--- a/"):
            f = line[6:]
            if f != "/dev/null": files.add(f)
    files.discard("/dev/null")
    return sorted(files)


def generate_one(task_row, oracle_files):
    file_contents = clone_and_read(task_row["repo"], task_row["base_commit"], oracle_files)
    if not file_contents:
        return {"model_patch": "", "changed_files": [], "error": "no files"}

    code_text = make_code_text(file_contents)
    prompt = PROMPT.format(
        problem_statement=task_row["problem_statement"],
        code_text=code_text,
        patch_example=PATCH_EXAMPLE,
    )

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_completion_tokens=4096,
    )

    raw = response.choices[0].message.content
    patch = extract_patch(raw)
    changed_files = extract_changed_files(patch)

    return {"model_patch": patch, "changed_files": changed_files, "raw": raw[:500]}


def main():
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    ds_map = {row["instance_id"]: row for row in ds}

    # Test 1 first
    iid = TASKS[0]
    row = ds_map[iid]
    print(f"Testing 1 task: {iid}...", end=" ", flush=True)
    result = generate_one(row, REF_FILES[iid])
    print(f"OK ({len(result['changed_files'])} files)")
    print(f"Patch preview:\n{result['model_patch'][:300]}")
    print()

    # Verify patch format - should NOT have fake index hashes
    has_fake_index = "index " in result["model_patch"].split("\n")[0] if result["model_patch"] else False
    print(f"Has index line: {has_fake_index}")
    print()

    # If test looks good, run all 20
    confirm = input("Run all 20? [y/n] ") if os.isatty(0) else "y"
    if confirm.lower() != "y":
        return

    with open(OUT_PATH, "w") as f:
        for i, iid in enumerate(TASKS):
            print(f"[{i+1}/{len(TASKS)}] {iid}...", end=" ", flush=True)
            row = ds_map[iid]
            try:
                result = generate_one(row, REF_FILES[iid])
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": result["model_patch"],
                    "changed_files": result["changed_files"],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
                print(f"OK ({len(result['changed_files'])} files: {result['changed_files'][:3]})")
            except Exception as e:
                print(f"ERROR: {e}")
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": "",
                    "changed_files": [],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
            time.sleep(0.5)

    print(f"\nDone. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
