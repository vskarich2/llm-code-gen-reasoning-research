"""Generate SWE-bench predictions using full-file replacement.

Model outputs the complete fixed file. We diff it against the original
programmatically to produce a clean patch for SWE-bench evaluation.
"""

import json, subprocess, tempfile, os, re, time, shutil, difflib
from pathlib import Path
from openai import OpenAI

TASKS = json.load(open("analysis/swebench_task_list.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
OUT_PATH = "analysis/swebench_predictions_v4.jsonl"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

PROMPT = """You will be provided with a partial code base and an issue statement explaining a problem to resolve.

<issue>
{problem_statement}
</issue>

<code>
{code_text}
</code>

I need you to solve the provided issue by modifying the source files shown above.

For EACH file you want to change, output the COMPLETE file contents with your fix applied. Use this exact format:

<fixed_file path="path/to/file.py">
complete file contents here
</fixed_file>

Rules:
- Output the ENTIRE file, not just the changed parts
- You may output multiple <fixed_file> blocks if multiple files need changes
- Only output files you are actually changing
- Fix the root cause, not symptoms

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


def extract_fixed_files(raw_response):
    """Extract fixed file contents from <fixed_file> tags."""
    files = {}
    pattern = r'<fixed_file\s+path="([^"]+)">(.*?)</fixed_file>'
    for match in re.finditer(pattern, raw_response, re.DOTALL):
        path = match.group(1).strip()
        content = match.group(2)
        # Strip leading/trailing newlines but preserve internal structure
        if content.startswith("\n"):
            content = content[1:]
        if content.endswith("\n"):
            content = content[:-1]
        content = content + "\n"  # ensure trailing newline
        files[path] = content
    return files


def make_unified_diff(original, fixed, filepath):
    """Generate a unified diff between original and fixed content."""
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    # Ensure trailing newlines
    if orig_lines and not orig_lines[-1].endswith("\n"):
        orig_lines[-1] += "\n"
    if fixed_lines and not fixed_lines[-1].endswith("\n"):
        fixed_lines[-1] += "\n"

    diff = difflib.unified_diff(
        orig_lines, fixed_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    )
    return "".join(diff)


def generate_one(task_row, oracle_files, originals):
    """Generate prediction for one task."""
    code_text = make_code_text(originals)
    prompt = PROMPT.format(
        problem_statement=task_row["problem_statement"],
        code_text=code_text,
    )

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_completion_tokens=65536,
    )

    raw = response.choices[0].message.content
    fixed_files = extract_fixed_files(raw)

    # Generate unified diff for each changed file
    patch_parts = []
    changed_files = []
    for filepath, fixed_content in fixed_files.items():
        if filepath in originals:
            diff = make_unified_diff(originals[filepath], fixed_content, filepath)
            if diff:
                patch_parts.append(diff)
                changed_files.append(filepath)

    full_patch = "\n".join(patch_parts)

    return {
        "model_patch": full_patch,
        "changed_files": changed_files,
        "fixed_files": list(fixed_files.keys()),
        "raw": raw[:500],
        "finish_reason": response.choices[0].finish_reason,
    }


def main():
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    ds_map = {row["instance_id"]: row for row in ds}

    # Test 1 first
    iid = TASKS[0]
    row = ds_map[iid]
    originals = clone_and_read(row["repo"], row["base_commit"], REF_FILES[iid])
    print(f"Test: {iid} ({len(originals)} files read)")
    result = generate_one(row, REF_FILES[iid], originals)
    print(f"  fixed_files: {result['fixed_files']}")
    print(f"  changed_files: {result['changed_files']}")
    print(f"  finish_reason: {result['finish_reason']}")
    print(f"  patch preview:")
    print(result["model_patch"][:400])
    print()

    # Verify patch applies
    tmpdir = tempfile.mkdtemp(prefix="swe_verify_")
    repo_dir = tmpdir + "/repo"
    subprocess.run(["git", "clone", "--depth", "1", f"https://github.com/{row['repo']}.git", repo_dir],
                   capture_output=True, timeout=120)
    subprocess.run(["git", "fetch", "--depth", "1", "origin", row["base_commit"]],
                   capture_output=True, cwd=repo_dir, timeout=60)
    subprocess.run(["git", "checkout", row["base_commit"]],
                   capture_output=True, cwd=repo_dir, timeout=30)
    Path(tmpdir + "/test.patch").write_text(result["model_patch"])
    r = subprocess.run(["git", "apply", "--check", tmpdir + "/test.patch"],
                      capture_output=True, text=True, cwd=repo_dir)
    print(f"  git apply --check: {'OK' if r.returncode == 0 else 'FAIL: ' + r.stderr[:200]}")
    shutil.rmtree(tmpdir, ignore_errors=True)

    if r.returncode != 0:
        print("  ABORTING — patch doesn't apply")
        return

    print("\nPatch applies cleanly. Running all 20 tasks...\n")

    with open(OUT_PATH, "w") as f:
        for i, iid in enumerate(TASKS):
            print(f"[{i+1}/{len(TASKS)}] {iid}...", end=" ", flush=True)
            row = ds_map[iid]
            try:
                originals = clone_and_read(row["repo"], row["base_commit"], REF_FILES[iid])
                result = generate_one(row, REF_FILES[iid], originals)
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": result["model_patch"],
                    "changed_files": result["changed_files"],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
                n = len(result["changed_files"])
                fr = result["finish_reason"]
                print(f"OK ({n} files: {result['changed_files'][:3]}) finish={fr}")
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
