"""Generate baseline predictions for golden 30 SWE-bench cases.

Full-file replacement approach: model sees all oracle files, outputs complete
fixed files. Diff computed programmatically for clean SWE-bench patches.
"""

import json, os, re, time, difflib
from openai import OpenAI

BASE = "analysis/swe_bench/"
CASES = json.load(open("runs/golden_30_cases.json"))
ALL_CONTENTS = {
    **json.load(open(BASE + "swebench_file_contents.json")),
    **json.load(open(BASE + "swebench_new_51_file_contents.json")),
}
ALL_REFS = {
    **json.load(open(BASE + "swebench_reference_files.json")),
    **json.load(open(BASE + "swebench_new_51_reference_files.json")),
}
ALL_INSTANCES = {}
for t in json.load(open(BASE + "swebench_task_instances.json")):
    ALL_INSTANCES[t["instance_id"]] = t
for t in json.load(open(BASE + "swebench_new_51_instances.json")):
    ALL_INSTANCES[t["instance_id"]] = t

OUT_PATH = "runs/golden_baseline_predictions.jsonl"

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


def generate_one(iid, oracle_files, file_contents, problem_statement,
                 extra_critique=None):
    code_text = make_code_text(file_contents)

    user_prompt = PROMPT.format(
        problem_statement=problem_statement,
        code_text=code_text,
    )

    if extra_critique:
        user_prompt += f"\n\nIMPORTANT FEEDBACK ON PREVIOUS ATTEMPT:\n{extra_critique}\n"

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_completion_tokens=128000,
    )

    raw = response.choices[0].message.content
    fixed_files = extract_fixed_files(raw)

    # Extract reasoning (first paragraph before fixed_file tags)
    reasoning = raw.split("<fixed_file")[0].strip()[:1000]

    patch_parts = []
    changed_files = []
    for filepath, fixed_content in fixed_files.items():
        if filepath in file_contents:
            diff = make_unified_diff(file_contents[filepath], fixed_content, filepath)
            if diff:
                patch_parts.append(diff)
                changed_files.append(filepath)

    full_patch = "\n".join(patch_parts)

    return {
        "model_patch": full_patch,
        "changed_files": changed_files,
        "fixed_files": list(fixed_files.keys()),
        "reasoning": reasoning,
        "finish_reason": response.choices[0].finish_reason,
    }


def main():
    # Test one first
    iid = CASES[0]
    oracle = ALL_REFS[iid]
    contents = {f: ALL_CONTENTS[iid][f] for f in oracle if f in ALL_CONTENTS.get(iid, {})}
    ps = ALL_INSTANCES[iid]["problem_statement"]
    print(f"Test: {iid} ({len(contents)} files)")

    result = generate_one(iid, oracle, contents, ps)
    print(f"  changed: {result['changed_files']}")
    print(f"  finish: {result['finish_reason']}")
    print(f"  patch len: {len(result['model_patch'])}")

    if not result["model_patch"]:
        print("  WARNING: empty patch")

    # Skip already-completed cases
    done = set()
    if os.path.exists(OUT_PATH):
        for line in open(OUT_PATH):
            d = json.loads(line)
            done.add(d["instance_id"])
        print(f"Skipping {len(done)} already-completed cases")

    remaining = [c for c in CASES if c not in done]
    print(f"\nRunning {len(remaining)} remaining cases (of {len(CASES)} total)...\n")

    with open(OUT_PATH, "a") as f:
        for i, iid in enumerate(remaining):
            print(f"[{i+1}/{len(remaining)}] {iid}...", end=" ", flush=True)
            oracle = ALL_REFS[iid]
            contents = {fp: ALL_CONTENTS[iid][fp] for fp in oracle
                        if fp in ALL_CONTENTS.get(iid, {})}
            ps = ALL_INSTANCES[iid]["problem_statement"]

            try:
                result = generate_one(iid, oracle, contents, ps)
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": result["model_patch"],
                    "reasoning": result["reasoning"],
                    "changed_files": result["changed_files"],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()

                oracle_set = set(oracle)
                changed_set = set(result["changed_files"])
                loc = "HIT" if oracle_set & changed_set else "MISS"
                print(f"OK ({len(result['changed_files'])} files) [{loc}] finish={result['finish_reason']}")
            except Exception as e:
                print(f"ERROR: {e}")
                pred = {
                    "instance_id": iid,
                    "model_name_or_path": "gpt-5.4-mini",
                    "model_patch": "",
                    "reasoning": f"ERROR: {e}",
                    "changed_files": [],
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
            time.sleep(0.5)

    print(f"\nDone. Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
