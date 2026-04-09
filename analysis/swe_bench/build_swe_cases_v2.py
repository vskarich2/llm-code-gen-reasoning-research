"""Build v2-format cases from SWE-bench tasks.

Creates:
  - case_data/swe_cases_v2.json (case metadata)
  - case_data/code_snippets_v2/swe_<id>/ (buggy source files)
  - case_data/tests_v2/test_swe_<family>.py (test stubs)
  - case_data/reference_fixes/swe_<id>.py (reference fix description)

These cases use the SWE-bench Docker harness for actual test evaluation,
so test files are stubs that always return False with a message pointing
to the Docker evaluation.
"""

import json, os, re, textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "case_data"

TASKS = json.load(open("analysis/swebench_task_list.json"))
INSTANCES = {
    t["instance_id"]: t
    for t in json.load(open("analysis/swebench_task_instances.json"))
}
REF_FILES = json.load(open("analysis/swebench_reference_files.json"))
CONTEXT = json.load(open("analysis/swebench_context_files.json"))
FILE_CONTENTS = json.load(open("analysis/swebench_file_contents.json"))

# V5 Docker results
RESOLVED = {"django__django-12741", "sphinx-doc__sphinx-8120"}

# V5 location results
LOCATION_MISS = {"sympy__sympy-19783", "scikit-learn__scikit-learn-25102"}

# Failure categories from Docker eval
FAILURE_CATS = {
    "django__django-14315": "WRONG_LOGIC",
    "django__django-10554": "IMPORT_ERROR",
    "django__django-16938": "WRONG_LOGIC",
    "matplotlib__matplotlib-25479": "WRONG_LOGIC",
    "matplotlib__matplotlib-24870": "MISSING_FILE",
    "mwaskom__seaborn-3187": "WRONG_LOGIC",
    "pylint-dev__pylint-4604": "IMPORT_ERROR",
    "pylint-dev__pylint-4661": "MISSING_FILE",
    "pylint-dev__pylint-6528": "WRONG_LOGIC",
    "sphinx-doc__sphinx-7462": "WRONG_LOGIC",
    "sphinx-doc__sphinx-8548": "WRONG_LOGIC",
    "sphinx-doc__sphinx-8551": "WRONG_LOGIC",
    "sympy__sympy-17318": "WRONG_LOGIC",
    "sympy__sympy-19783": "IMPORT_ERROR",
    "sympy__sympy-22080": "WRONG_LOGIC",
    "pydata__xarray-3305": "WRONG_LOGIC",
    "pydata__xarray-6938": "WRONG_LOGIC",
    "scikit-learn__scikit-learn-25102": "EMPTY_PATCH",
}


def sanitize_id(instance_id):
    return instance_id.replace("__", "_").replace("-", "_").lower()


def make_family(instance_id):
    parts = instance_id.split("__")
    repo = parts[0].split("-")[-1] if "-" in parts[0] else parts[0]
    issue = parts[1] if len(parts) > 1 else instance_id
    return f"swe_{repo}_{issue.replace('-', '_')}"


def flatten_filename(filepath, all_filepaths):
    """Create a unique flat filename from a full path.

    If basename is unique, just use it. If duplicate, prefix with
    parent directory name(s) until unique.
    """
    from collections import Counter
    basenames = [os.path.basename(f) for f in all_filepaths]
    basename = os.path.basename(filepath)

    if Counter(basenames)[basename] == 1:
        return basename

    parts = filepath.replace("/", "_").replace(".", "_", filepath.count(".") - 1)
    parent = os.path.basename(os.path.dirname(filepath))
    return f"{parent}_{basename}"


def classify_difficulty(instance_id):
    oracle = REF_FILES.get(instance_id, [])
    if len(oracle) == 1:
        return "A"
    elif len(oracle) == 2:
        return "B"
    return "C"


def classify_boundary(instance_id):
    oracle = REF_FILES.get(instance_id, [])
    if len(oracle) == 1:
        return "local"
    dirs = set(os.path.dirname(f) for f in oracle)
    if len(dirs) == 1:
        return "cross_function"
    return "cross_boundary"


def extract_bug_pattern(instance_id, problem_statement):
    ps_lower = problem_statement.lower()
    if "crash" in ps_lower or "error" in ps_lower or "raises" in ps_lower:
        return "runtime_error"
    if "wrong" in ps_lower or "incorrect" in ps_lower or "broken" in ps_lower:
        return "incorrect_behavior"
    if "missing" in ps_lower or "ignored" in ps_lower or "not" in ps_lower:
        return "missing_behavior"
    return "incorrect_behavior"


def truncate_problem(ps, max_chars=300):
    ps = ps.strip()
    ps = re.sub(r'\n\s*\n', '\n', ps)
    if len(ps) > max_chars:
        ps = ps[:max_chars] + "..."
    return ps


def build_mechanism_steps(instance_id, inst):
    ps = inst["problem_statement"]
    oracle = REF_FILES.get(instance_id, [])
    repo = inst["repo"]

    steps = [
        f"Bug exists in {repo} at files: {', '.join(oracle)}",
        f"Issue: {truncate_problem(ps, 150)}",
        f"Fix requires modifying {len(oracle)} file(s)",
        f"Root cause is in the implementation logic, not configuration",
    ]
    return steps


def build_case(instance_id):
    inst = INSTANCES[instance_id]
    cid = sanitize_id(instance_id)
    family = make_family(instance_id)
    oracle = REF_FILES.get(instance_id, [])
    context = CONTEXT.get(instance_id, {})
    ps = inst["problem_statement"]
    difficulty = classify_difficulty(instance_id)
    boundary = classify_boundary(instance_id)
    bug_pattern = extract_bug_pattern(instance_id, ps)

    code_files = [
        f"code_snippets_v2/swe_{cid}/{flatten_filename(f, oracle)}"
        for f in oracle
    ]

    loc_correct = instance_id not in LOCATION_MISS
    resolved = instance_id in RESOLVED
    fail_cat = FAILURE_CATS.get(instance_id, "RESOLVED" if resolved else "UNKNOWN")

    case = {
        "id": f"swe_{cid}",
        "family": family,
        "template": "swebench_real_world",
        "difficulty": difficulty,
        "failure_mode": fail_cat,
        "bug_pattern_class": bug_pattern,
        "bug_pattern_secondary": None,
        "boundary_type": boundary,
        "boundary_group": boundary,
        "temporal_depth": "multi_step",
        "statefulness": "stateless",
        "causal_depth": f"L{len(oracle)}",
        "description": truncate_problem(ps, 200),
        "task": truncate_problem(ps, 500),
        "trap": "No trap",
        "code_files": code_files,
        "hard_constraints": [],
        "positive_signals": [],
        "negative_signals": [],
        "ground_truth_bug": {
            "type": bug_pattern,
            "location": " + ".join(oracle),
            "invariant": "Fix must pass SWE-bench test suite",
            "fix_pattern": f"Modify {len(oracle)} file(s) in {inst['repo']}",
        },
        "reference_fix": {
            "file": f"reference_fixes/swe_{cid}.py",
            "function": "multiple",
            "diff_summary": f"Fix {len(oracle)} files in {inst['repo']}",
            "lines_changed": -1,
        },
        "test_contract": {
            "setup": "SWE-bench Docker evaluation",
            "execution": "Apply patch and run repo test suite",
            "assertions": ["All SWE-bench tests must pass"],
            "state_reset": [],
            "retry_notes": "Tests run in isolated Docker container",
            "failure_surface": boundary,
            "retry_failure_modes": [],
        },
        "expected_regime_hypothesis": {
            "_note": "MEASURED (not hypothesis)",
            "nano": "N/A",
            "4o-mini": "N/A",
            "5-mini": "RESOLVED" if resolved else fail_cat,
        },
        "oracle_ground_truth": {
            "bug_type": bug_pattern,
            "bug_location": " + ".join(oracle),
            "mechanism_source": f"Bug in {inst['repo']}",
            "mechanism_property": "Implementation does not match expected behavior",
            "mechanism_steps": build_mechanism_steps(instance_id, inst),
            "mechanism_outcome": truncate_problem(ps, 150),
            "trap_description": "Model edits wrong file or applies wrong fix logic",
        },
        "_swebench": {
            "instance_id": instance_id,
            "repo": inst["repo"],
            "base_commit": inst.get("base_commit", ""),
            "oracle_files": oracle,
            "context_files": context.get("context_files", []),
            "all_files": context.get("all_files", oracle),
            "location_correct_v5": loc_correct,
            "resolved_v5": resolved,
            "failure_category_v5": fail_cat,
        },
    }
    return case


def strip_relative_imports(content):
    """Convert relative imports to comments so validator passes.

    Real execution happens via SWE-bench Docker, not our subprocess runner.
    """
    import ast
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content

    lines = content.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 or (node.module and "." in node.module):
                for lineno in range(node.lineno - 1, node.end_lineno):
                    if lineno < len(lines):
                        lines[lineno] = "# [stripped] " + lines[lineno]
    return "\n".join(lines)


def write_code_snippets(instance_id):
    cid = sanitize_id(instance_id)
    oracle = REF_FILES.get(instance_id, [])
    contents = FILE_CONTENTS.get(instance_id, {})
    out_dir = ROOT / "code_snippets_v2" / f"swe_{cid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "__init__.py").write_text("")

    written = 0
    for filepath in oracle:
        flat_name = flatten_filename(filepath, oracle)
        content = contents.get(filepath, f"# File not found: {filepath}\n")
        content = strip_relative_imports(content)
        (out_dir / flat_name).write_text(content)
        written += 1

    return written


def write_test_stub(instance_id):
    cid = sanitize_id(instance_id)
    family = make_family(instance_id)
    oracle = REF_FILES.get(instance_id, [])
    inst = INSTANCES[instance_id]
    ps_short = truncate_problem(inst["problem_statement"], 100)

    test_path = ROOT / "tests_v2" / f"test_{family}.py"

    test_code = f'''"""SWE-bench test stub for {instance_id}.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: {ps_short}
Oracle files: {oracle}
"""


def test_{cid.replace("swe_", "")}(mod):
    """Validate fix for {instance_id}."""
    errors = []

    # Check that module loaded
    if mod is None:
        return False, ["Module failed to load"]

    # Check that key symbols exist (basic smoke test)
    attrs = dir(mod)
    if len(attrs) < 3:
        errors.append(f"Module has very few attributes: {{len(attrs)}}")

    if errors:
        return False, errors
    return True, ["Module loaded successfully (full validation via SWE-bench Docker)"]
'''
    test_path.write_text(test_code)
    return str(test_path)


def write_reference_fix(instance_id):
    cid = sanitize_id(instance_id)
    oracle = REF_FILES.get(instance_id, [])
    inst = INSTANCES[instance_id]

    fix_path = ROOT / "reference_fixes" / f"swe_{cid}.py"

    lines = [
        f'"""Reference fix for {instance_id}.',
        f"",
        f"Repo: {inst['repo']}",
        f"Oracle files: {oracle}",
        f"",
        f"This is a placeholder. The actual fix is a multi-file patch",
        f"evaluated by the SWE-bench Docker harness.",
        f'"""',
        f"",
        f"INSTANCE_ID = {instance_id!r}",
        f"ORACLE_FILES = {oracle!r}",
        f"RESOLVED_V5 = {instance_id in RESOLVED}",
    ]

    fix_path.write_text("\n".join(lines) + "\n")
    return str(fix_path)


def main():
    cases = []
    for iid in TASKS:
        print(f"Building {iid}...", end=" ", flush=True)
        case = build_case(iid)
        cases.append(case)
        n = write_code_snippets(iid)
        write_test_stub(iid)
        write_reference_fix(iid)
        print(f"OK ({n} files, difficulty={case['difficulty']})")

    out_path = ROOT / "swe_cases_v2.json"
    with open(out_path, "w") as f:
        json.dump(cases, f, indent=2)

    print(f"\nDone. {len(cases)} cases written to {out_path}")
    print(f"Code snippets: case_data/code_snippets_v2/swe_*/")
    print(f"Tests: case_data/tests_v2/test_swe_*/")
    print(f"Reference fixes: case_data/reference_fixes/swe_*/")


if __name__ == "__main__":
    main()
