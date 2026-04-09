"""Generate SWE-bench predictions with import-linked context files.

Key difference from v4: model sees ALL files (oracle + context), not just
oracle files. This makes location accuracy a real metric — the model must
choose which files to edit from a larger set.

Uses pre-fetched file contents from swebench_file_contents.json.
"""

import json, subprocess, tempfile, os, re, time, shutil, difflib
from pathlib import Path
from openai import OpenAI

TASKS = json.load(open("analysis/swebench_task_list.json"))
CONTEXT = json.load(open("analysis/swebench_context_files.json"))
FILE_CONTENTS = json.load(open("analysis/swebench_file_contents.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
OUT_PATH = "analysis/swebench_predictions_v5.jsonl"

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


def make_code_text(file_contents):
    parts = []
    for path, content in file_contents.items():
        parts.append(f"[start of {path}]")
        parts.append(content)
        parts.append(f"[end of {path}]")
    return "\n".join(parts)


def extract_fixed_files(raw_response):
    files = {}
    pattern = r'<fixed_file\s+path="([^"]+)">(.*?)</fixed_file>'
    for match in re.finditer(pattern, raw_response, re.DOTALL):
        path = match.group(1).strip()
        content = match.group(2)
        if content.startswith("\n"):
            content = content[1:]
        if content.endswith("\n"):
            content = content[:-1]
        content = content + "\n"
        files[path] = content
    return files


def make_unified_diff(original, fixed, filepath):
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
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


def generate_one(task_row, all_file_contents):
    code_text = make_code_text(all_file_contents)
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

    patch_parts = []
    changed_files = []
    for filepath, fixed_content in fixed_files.items():
        if filepath in all_file_contents:
            diff = make_unified_diff(
                all_file_contents[filepath], fixed_content, filepath
            )
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
    all_files = FILE_CONTENTS.get(iid, {})
    oracle_files = REF_FILES[iid]
    n_oracle = len(oracle_files)
    n_total = len(all_files)
    print(f"Test: {iid}")
    print(f"  Oracle files ({n_oracle}): {oracle_files}")
    print(f"  Total files ({n_total}): {list(all_files.keys())}")

    result = generate_one(row, all_files)
    print(f"  fixed_files: {result['fixed_files']}")
    print(f"  changed_files: {result['changed_files']}")
    print(f"  finish_reason: {result['finish_reason']}")
    print(f"  patch preview:")
    print(result["model_patch"][:400])

    # Check location accuracy for this one
    oracle_set = set(oracle_files)
    changed_set = set(result["changed_files"])
    hit = bool(oracle_set & changed_set)
    all_hit = oracle_set <= changed_set
    print(f"\n  Location hit: {hit}")
    print(f"  All oracle files hit: {all_hit}")
    print(f"  Oracle files changed: {oracle_set & changed_set}")
    print(f"  Non-oracle files changed: {changed_set - oracle_set}")

    if not result["model_patch"]:
        print("\n  WARNING: empty patch, aborting")
        return

    print("\nTest OK. Running all 20 tasks...\n")

    loc_hits = 0
    all_hits = 0
    with open(OUT_PATH, "w") as f:
        for i, iid in enumerate(TASKS):
            print(f"[{i+1}/{len(TASKS)}] {iid}...", end=" ", flush=True)
            row = ds_map[iid]
            all_files = FILE_CONTENTS.get(iid, {})
            oracle_files_set = set(REF_FILES[iid])

            try:
                result = generate_one(row, all_files)
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": result["model_patch"],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()

                changed = set(result["changed_files"])
                hit = bool(oracle_files_set & changed)
                ahit = oracle_files_set <= changed
                loc_hits += int(hit)
                all_hits += int(ahit)

                n = len(result["changed_files"])
                fr = result["finish_reason"]
                extra = changed - oracle_files_set
                marker = "ALL" if ahit else ("HIT" if hit else "MISS")
                print(
                    f"OK ({n} files) [{marker}] "
                    f"oracle={sorted(oracle_files_set & changed)} "
                    f"extra={sorted(extra)} finish={fr}"
                )
            except Exception as e:
                print(f"ERROR: {e}")
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": "",
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
            time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"Location accuracy (any oracle file): {loc_hits}/{len(TASKS)}")
    print(f"All oracle files hit:                {all_hits}/{len(TASKS)}")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
