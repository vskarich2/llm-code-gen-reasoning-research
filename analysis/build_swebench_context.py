#!/usr/bin/env python3
"""Build context file mappings for SWE-bench tasks.

For each task:
1. Clone the repo at base_commit
2. Read oracle files
3. Parse imports via ast
4. Resolve imports to repo-relative paths
5. Find reverse dependencies (files that import oracle files)
6. Cap at 10 context files per task (proximity-sorted)
7. Output analysis/swebench_context_files.json
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TASK_LIST_PATH = SCRIPT_DIR / "swebench_task_list.json"
TASK_INSTANCES_PATH = SCRIPT_DIR / "swebench_task_instances.json"
REFERENCE_FILES_PATH = SCRIPT_DIR / "swebench_reference_files.json"
OUTPUT_PATH = SCRIPT_DIR / "swebench_context_files.json"

MAX_CONTEXT_FILES = 10
MAX_WORKERS = 5

# Common source root subdirectories in Python repos
SOURCE_ROOT_CANDIDATES = ["lib", "src", "source"]


def detect_source_roots(repo_root, oracle_files):
    """Detect source root directories within a repo.

    Some repos (e.g. matplotlib) store code under lib/.
    Returns a list of repo-relative source root prefixes (e.g. ['lib']).
    The repo root itself is always included (as empty string).
    """
    roots = [""]
    for candidate in SOURCE_ROOT_CANDIDATES:
        candidate_path = Path(repo_root) / candidate
        if candidate_path.is_dir():
            for of in oracle_files:
                if of.startswith(candidate + "/"):
                    roots.append(candidate)
                    break
    return roots


def load_inputs():
    """Load task list, task instances, and reference files."""
    with open(TASK_LIST_PATH) as f:
        task_list = json.load(f)
    with open(TASK_INSTANCES_PATH) as f:
        task_instances_raw = json.load(f)
    with open(REFERENCE_FILES_PATH) as f:
        reference_files = json.load(f)

    task_instances = {
        item["instance_id"]: item for item in task_instances_raw
    }
    return task_list, task_instances, reference_files


def clone_repo_at_commit(repo, base_commit, dest_dir):
    """Clone a GitHub repo and checkout a specific commit."""
    url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--quiet", url, dest_dir],
        check=True,
        capture_output=True,
        timeout=300,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", base_commit],
        cwd=dest_dir,
        check=True,
        capture_output=True,
        timeout=60,
    )


def parse_imports_from_file(filepath):
    """Parse a Python file and return a list of import targets.

    Returns list of tuples: (module_path, imported_names)
    For 'import foo.bar' -> ('foo.bar', [])
    For 'from foo.bar import X, Y' -> ('foo.bar', ['X', 'Y'])
    """
    try:
        source = Path(filepath).read_text(errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, []))
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            names = [alias.name for alias in node.names]
            imports.append((node.module, names))
    return imports


def module_to_possible_paths(module_path):
    """Convert a dotted module path to possible file paths.

    'django.db.models' -> [
        'django/db/models/__init__.py',
        'django/db/models.py',
    ]
    """
    parts = module_path.split(".")
    base = "/".join(parts)
    return [
        f"{base}/__init__.py",
        f"{base}.py",
    ]


def resolve_import_to_file(module_path, repo_root, source_roots):
    """Resolve a dotted module to a repo-relative file path.

    Tries each source root prefix to find the actual file.
    """
    candidates = module_to_possible_paths(module_path)
    for src_root in source_roots:
        for candidate in candidates:
            if src_root:
                full_candidate = f"{src_root}/{candidate}"
            else:
                full_candidate = candidate
            full = Path(repo_root) / full_candidate
            if full.is_file():
                return full_candidate
    return None


def file_path_to_module(filepath, source_roots=None):
    """Convert a repo-relative .py file path to a dotted module path.

    'django/db/models/sql/compiler.py' -> 'django.db.models.sql.compiler'
    'django/db/models/__init__.py' -> 'django.db.models'
    'lib/matplotlib/cm.py' (with source_roots=['lib'])
        -> 'matplotlib.cm'
    """
    if source_roots is None:
        source_roots = [""]
    stripped = filepath
    for sr in source_roots:
        if sr and filepath.startswith(sr + "/"):
            stripped = filepath[len(sr) + 1 :]
            break
    p = stripped.replace("/", ".")
    if p.endswith(".__init__.py"):
        p = p[: -len(".__init__.py")]
    elif p.endswith(".py"):
        p = p[: -len(".py")]
    return p


def compute_proximity_key(context_file, oracle_files):
    """Compute a proximity score for sorting context files.

    Lower score = closer to an oracle file.
    0 = same directory, 1 = one directory up, etc.
    """
    best = float("inf")
    ctx_parts = Path(context_file).parent.parts
    for oracle in oracle_files:
        oracle_parts = Path(oracle).parent.parts
        common_len = 0
        for a, b in zip(ctx_parts, oracle_parts):
            if a == b:
                common_len += 1
            else:
                break
        max_depth = max(len(ctx_parts), len(oracle_parts))
        distance = max_depth - common_len
        if distance < best:
            best = distance
    return best


def find_reverse_dependencies(oracle_files, repo_root):
    """Find .py files in the same package dirs that import any oracle file.

    Scans .py files in each oracle file's directory and parent directory.
    """
    oracle_modules = set()
    for of in oracle_files:
        oracle_modules.add(file_path_to_module(of))

    dirs_to_scan = set()
    for of in oracle_files:
        parent = Path(repo_root) / Path(of).parent
        dirs_to_scan.add(parent)
        grandparent = parent.parent
        if grandparent != Path(repo_root).parent:
            dirs_to_scan.add(grandparent)

    oracle_set = set(oracle_files)
    reverse_deps = set()

    for scan_dir in dirs_to_scan:
        if not scan_dir.is_dir():
            continue
        for py_file in scan_dir.glob("*.py"):
            rel = str(py_file.relative_to(repo_root))
            if rel in oracle_set:
                continue
            imports = parse_imports_from_file(py_file)
            for module_path, _names in imports:
                if module_path in oracle_modules:
                    reverse_deps.add(rel)
                    break
                for om in oracle_modules:
                    if module_path.startswith(om + "."):
                        reverse_deps.add(rel)
                        break
                    if om.startswith(module_path + "."):
                        reverse_deps.add(rel)
                        break

    return reverse_deps


def process_task(instance_id, task_instances, reference_files):
    """Process a single SWE-bench task and return context data."""
    if instance_id not in task_instances:
        raise ValueError(
            f"Instance {instance_id} not found in task instances"
        )
    if instance_id not in reference_files:
        raise ValueError(
            f"Instance {instance_id} not found in reference files"
        )

    task = task_instances[instance_id]
    repo = task["repo"]
    base_commit = task["base_commit"]
    oracle_files = reference_files[instance_id]

    tmpdir = tempfile.mkdtemp(prefix=f"swebench_{instance_id}_")
    try:
        clone_repo_at_commit(repo, base_commit, tmpdir)

        forward_deps = set()
        for of in oracle_files:
            full_path = Path(tmpdir) / of
            if not full_path.is_file():
                continue
            imports = parse_imports_from_file(full_path)
            for module_path, _names in imports:
                resolved = resolve_import_to_file(module_path, tmpdir)
                if resolved and resolved not in oracle_files:
                    forward_deps.add(resolved)

        reverse_deps = find_reverse_dependencies(oracle_files, tmpdir)

        all_context = forward_deps | reverse_deps
        oracle_set = set(oracle_files)
        all_context -= oracle_set

        sorted_context = sorted(
            all_context,
            key=lambda f: (
                compute_proximity_key(f, oracle_files),
                f,
            ),
        )
        capped = sorted_context[:MAX_CONTEXT_FILES]

        all_files = sorted(set(oracle_files) | set(capped))

        return {
            "oracle_files": oracle_files,
            "context_files": capped,
            "all_files": all_files,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    """Main entry point."""
    from dotenv import load_dotenv
    import os

    load_dotenv()

    HF_TOKEN = os.environ["HF_TOKEN"]

    task_list, task_instances, reference_files = load_inputs()
    print(f"Loaded {len(task_list)} tasks")

    results = {}
    failed = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {
            executor.submit(
                process_task, iid, task_instances, reference_files
            ): iid
            for iid in task_list
        }

        for future in as_completed(future_to_id):
            iid = future_to_id[future]
            try:
                result = future.result()
                results[iid] = result
                n_ctx = len(result["context_files"])
                n_all = len(result["all_files"])
                print(
                    f"  [OK] {iid}: "
                    f"{n_ctx} context files, "
                    f"{n_all} total files"
                )
            except Exception as exc:
                failed.append(iid)
                print(f"  [FAIL] {iid}: {exc}", file=sys.stderr)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone. {len(results)} tasks processed, {len(failed)} failed.")
    print(f"Output written to {OUTPUT_PATH}")

    if failed:
        print(f"Failed tasks: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
