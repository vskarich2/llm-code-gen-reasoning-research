"""Generate gpt-5.4-mini predictions for 20 SWE-bench Verified tasks.

Sends each problem statement to the model and asks for a unified diff patch.
Saves predictions to analysis/swebench_predictions.jsonl.
"""

import json
import os
import re
import time

TASKS = json.load(open("analysis/swebench_task_instances.json"))
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
OUT_PATH = "analysis/swebench_predictions.jsonl"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY")

from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_TEMPLATE = """You are a software engineer fixing a bug in an open-source Python project.

Repository: {repo}

Problem description:
{problem_statement}

{hints}

Produce a unified diff patch that fixes this bug. The patch should be applicable with `git apply`.

Rules:
- Output ONLY the patch (unified diff format)
- Include file paths relative to the repo root
- Do not include test file changes
- Fix the root cause, not symptoms

Output your patch now:"""


def extract_changed_files(patch_text):
    """Extract file paths from a unified diff or model-generated patch format."""
    files = set()
    for line in patch_text.split("\n"):
        # Standard unified diff
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) >= 2:
                files.add(parts[-1])
        elif line.startswith("+++ b/"):
            files.add(line[6:])
        elif line.startswith("--- a/"):
            files.add(line[6:])
        # Model format: *** Update File: path/to/file.py
        elif line.startswith("*** Update File:"):
            f = line.split("*** Update File:")[-1].strip()
            if f:
                files.add(f)
        # Model format: --- path/to/file.py
        elif line.startswith("--- ") and not line.startswith("--- a/"):
            f = line[4:].strip()
            if f and "/" in f and not f.startswith("+++"):
                files.add(f)
    # Remove /dev/null
    files.discard("/dev/null")
    files.discard("dev/null")
    return sorted(files)


def generate_prediction(task):
    hints = ""
    if task.get("hints_text"):
        hints = f"Hints:\n{task['hints_text']}"

    prompt = PROMPT_TEMPLATE.format(
        repo=task["repo"],
        problem_statement=task["problem_statement"],
        hints=hints,
    )

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_completion_tokens=4096,
    )

    raw = response.choices[0].message.content

    # Extract patch from markdown fences if present
    patch = raw
    if "```" in raw:
        blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", raw, re.DOTALL)
        if blocks:
            patch = blocks[0]

    changed_files = extract_changed_files(patch)

    return {
        "instance_id": task["instance_id"],
        "model_name_or_path": "gpt-5.4-mini",
        "model": "gpt-5.4-mini",
        "patch": patch.strip(),
        "changed_files": changed_files,
        "reasoning": raw[:500],
    }


def main():
    results = []
    with open(OUT_PATH, "w") as f:
        for i, task in enumerate(TASKS):
            print(f"[{i+1}/{len(TASKS)}] {task['instance_id']}...", end=" ", flush=True)
            try:
                pred = generate_prediction(task)
                f.write(json.dumps(pred) + "\n")
                f.flush()
                results.append(pred)
                n_files = len(pred["changed_files"])
                print(f"OK ({n_files} files: {pred['changed_files'][:3]})")
            except Exception as e:
                print(f"ERROR: {e}")
                pred = {
                    "instance_id": task["instance_id"],
                    "model_name_or_path": "gpt-5.4-mini",
                    "model": "gpt-5.4-mini",
                    "patch": "",
                    "changed_files": [],
                    "reasoning": f"ERROR: {e}",
                }
                f.write(json.dumps(pred) + "\n")
                f.flush()
                results.append(pred)
            time.sleep(0.5)

    print(f"\nDone. {len(results)} predictions saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
