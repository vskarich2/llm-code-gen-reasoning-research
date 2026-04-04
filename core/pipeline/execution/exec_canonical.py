"""Canonical disk-backed execution.

One public function. Owns materialization, subprocess, validation,
classification. All internal functions in this file, not exported.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core.config.paths import PROJECT_ROOT as _PROJECT_ROOT
PROJECT_ROOT = str(_PROJECT_ROOT)

# ── Taxonomy ─────────────────────────────────────────────────────

ALL_CATEGORIES = frozenset({
    "PARSE_FAILURE", "RECONSTRUCTION_FAILURE", "BUILD_FAILURE",
    "SUBPROCESS_CRASH", "INVALID_OUTPUT", "SCHEMA_VIOLATION",
    "TIMEOUT", "SYNTAX_FAILURE", "IMPORT_FAILURE", "NAME_ERROR",
    "INVARIANT_CRASH", "INVARIANT_FAILURE", "EXECUTION_SUCCESS",
    "STRUCTURAL_FAILURE",
})

REQUIRED_SUBPROCESS_FIELDS = frozenset({
    "status", "passed", "failure_reasons", "error_type",
    "error_message", "traceback", "modules_loaded",
    "functions_detected", "functions_called", "merge_conflicts",
    "execution_trace", "execution_time_ms",
})


# ── Validation ───────────────────────────────────────────────────

def _validate(result):
    """Validate subprocess output schema. Raises ValueError on failure."""
    missing = REQUIRED_SUBPROCESS_FIELDS - set(result.keys())
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if not isinstance(result["passed"], bool):
        raise ValueError(
            f"'passed' must be bool, got {type(result['passed'])}")
    for field in ("failure_reasons", "modules_loaded",
                  "functions_detected", "functions_called",
                  "merge_conflicts", "execution_trace"):
        if not isinstance(result[field], list):
            raise ValueError(
                f"'{field}' must be list, got {type(result[field])}")
    if not isinstance(result["execution_time_ms"], (int, float)):
        raise ValueError("'execution_time_ms' must be numeric")


# ── Classification ───────────────────────────────────────────────

def _classify(result):
    """Map subprocess result to (category, score). No fallback."""
    status = result.get("status", "")
    err = result.get("error_type") or ""

    if status == "timeout":
        return "TIMEOUT", 0.0
    if status == "crash":
        return "SUBPROCESS_CRASH", 0.0
    if status == "invalid_output":
        return "INVALID_OUTPUT", 0.0
    if err == "SyntaxError":
        return "SYNTAX_FAILURE", 0.0
    if err in ("ImportError", "ModuleNotFoundError"):
        return "IMPORT_FAILURE", 0.0
    if err == "NameError":
        return "NAME_ERROR", 0.0
    if err and status == "error":
        return "INVARIANT_CRASH", 0.1
    if status == "ok" and not result.get("passed", False):
        return "INVARIANT_FAILURE", 0.2
    if status == "ok" and result.get("passed", False):
        return "EXECUTION_SUCCESS", 1.0

    raise RuntimeError(f"Unclassifiable subprocess result: {result}")


# ── Package materialization ──────────────────────────────────────

def _materialize_package(case, recon, project_root, attempt):
    """Create temp dir with pkg/, harness/, case_meta.json."""
    case_id = case["id"]
    pkg_dir = Path(tempfile.mkdtemp(
        prefix=f"t3_eval_{case_id}_attempt{attempt}_"))

    # pkg/
    pkg = pkg_dir / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    # Write code files
    for rel_path in case["code_files"]:
        filename = rel_path.rsplit("/", 1)[-1]
        if rel_path in recon.changed_files:
            content = recon.files[rel_path]
        else:
            content = case["code_files_contents"][rel_path]
        (pkg / filename).write_text(content)

    # harness/
    harness_dst = pkg_dir / "harness"
    harness_dst.mkdir()
    from core.config.paths import HARNESS_SCRIPT
    harness_src = HARNESS_SCRIPT
    shutil.copy2(str(harness_src), str(harness_dst / "run_case.py"))

    # case_meta.json
    meta = {
        "case_id": case_id,
        "family": case.get("family", ""),
        "difficulty": case.get("difficulty", "a").lower(),
        "project_root": project_root,
        "code_files": case["code_files"],
    }
    (pkg_dir / "case_meta.json").write_text(json.dumps(meta))

    return pkg_dir


# ── Subprocess execution ─────────────────────────────────────────

def _run_subprocess(pkg_dir, project_root, timeout=30):
    """Spawn subprocess, parse stdout as JSON. Returns dict."""
    env = os.environ.copy()
    pkg_path = str(pkg_dir / "pkg")
    case_data_dir = os.path.join(project_root, "case_data")
    env["PYTHONPATH"] = f"{pkg_path}{os.pathsep}{project_root}{os.pathsep}{case_data_dir}"

    cmd = [sys.executable, "harness/run_case.py"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(pkg_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "timeout_seconds": timeout}

    if proc.returncode != 0:
        return {
            "status": "crash",
            "exit_code": proc.returncode,
            "stderr": (proc.stderr or ""),
            "stdout": (proc.stdout or ""),
        }

    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return {
            "status": "invalid_output",
            "stdout": (proc.stdout or ""),
            "stderr": (proc.stderr or ""),
        }

    return parsed


# ── Result builder ───────────────────────────────────────────────

def _make_result(case, subprocess_result, category, score, ran):
    """Build exec_evaluate-compatible return dict."""
    # Consistency checks
    if not ran and category == "EXECUTION_SUCCESS":
        raise RuntimeError(
            "Invalid state: EXECUTION_SUCCESS without execution")
    if ran and category in (
            "PARSE_FAILURE", "RECONSTRUCTION_FAILURE", "BUILD_FAILURE"):
        raise RuntimeError(
            f"Invalid state: {category} but ran=True")
    if category not in ALL_CATEGORIES:
        raise RuntimeError(f"Unknown category: {category}")

    passed = category == "EXECUTION_SUCCESS"

    # execution sub-dict
    if passed:
        exec_status = "passed"
    elif category == "INVARIANT_FAILURE":
        exec_status = "failed"
    elif ran:
        exec_status = "error"
    else:
        exec_status = "not_executed"

    execution = {
        "status": exec_status,
        "ran": ran,
        "passed_tests": 1 if passed else 0,
        "total_tests": 1 if ran else 0,
        "runtime_error": (subprocess_result.get("error_message")
                          if ran else None),
        "error_message": (subprocess_result.get("error_message")
                          if ran else None),
        "syntax_error": (subprocess_result.get("error_message")
                         if category == "SYNTAX_FAILURE" else None),
        "assembly_used": False,
        "assembly_error": False,
        "assembly_risky": False,
        "rename_error": False,
        "assembly_sources": None,
        "invariant_pass": passed if ran else None,
        "mutation_pass": None,
    }

    # reasons
    reasons = subprocess_result.get("failure_reasons", []) if ran else []
    if not passed and not reasons:
        err_msg = subprocess_result.get("error_message")
        if err_msg:
            reasons = [err_msg]

    return {
        "pass": passed,
        "score": score,
        "reasons": reasons,
        "failure_modes": (
            [case.get("failure_mode", "")]
            if not passed else []),
        "execution": execution,
        "execution_category": category,
        "execution_subtype": subprocess_result.get("error_type"),
        "modules_loaded": subprocess_result.get("modules_loaded", []),
        "functions_detected": subprocess_result.get(
            "functions_detected", []),
        "functions_called": subprocess_result.get(
            "functions_called", []),
        "merge_conflicts": subprocess_result.get(
            "merge_conflicts", []),
        "execution_trace": subprocess_result.get(
            "execution_trace", []),
        "reconstruction_status": None,  # set by caller
        "semantic_diagnostics": {
            "missing_required_definitions": False,
            "missing_definition_names": [],
        },  # set by caller
        "_extracted_code": "",
        "_assembled_code": "disk_backed",
    }


# ── Public API ───────────────────────────────────────────────────

def exec_canonical(case, parsed_gen, recon, config, logger, attempt=0):
    """Canonical disk-backed execution.

    1. Materialize package on disk
    2. Spawn subprocess
    3. Validate + classify result
    4. Build return dict
    5. Write artifacts (if configured)
    6. Emit WAL event
    7. Cleanup

    Returns exec_evaluate-compatible dict.
    """
    project_root = PROJECT_ROOT

    # ── Pre-execution checks ─────────────────────────────────
    if recon.status != "SUCCESS":
        reasons = [f"reconstruction failed: {recon.status}"]
        if recon.syntax_errors:
            reasons.append(
                f"syntax errors: {list(recon.syntax_errors.keys())}")
        if recon.missing_files:
            reasons.append(
                f"missing files: {sorted(recon.missing_files)}")
        result = _make_result(
            case,
            {"error_message": reasons[0], "failure_reasons": reasons},
            "RECONSTRUCTION_FAILURE", 0.0, ran=False)
        result["reconstruction_status"] = recon.status
        return result

    # ── Materialize ──────────────────────────────────────────
    pkg_dir = None
    try:
        pkg_dir = _materialize_package(
            case, recon, project_root, attempt)
    except Exception as e:
        return _make_result(
            case,
            {"error_type": type(e).__name__,
             "error_message": str(e)},
            "BUILD_FAILURE", 0.0, ran=False)

    try:
        # ── Subprocess ───────────────────────────────────────
        timeout = config.execution.subprocess_timeout

        subprocess_result = _run_subprocess(
            pkg_dir, project_root, timeout)

        # ── Validate + Classify ──────────────────────────────
        status = subprocess_result.get("status", "")
        if status in ("timeout", "crash", "invalid_output"):
            category, score = _classify(subprocess_result)
        else:
            try:
                _validate(subprocess_result)
            except ValueError:
                category, score = "SCHEMA_VIOLATION", 0.0
            else:
                category, score = _classify(subprocess_result)

        # ── Build result ─────────────────────────────────────
        result = _make_result(
            case, subprocess_result, category, score, ran=True)

        # Set extracted code from recon
        extracted = []
        for rel_path in case["code_files"]:
            if rel_path in recon.changed_files:
                extracted.append(recon.files.get(rel_path, ""))
        result["_extracted_code"] = "\n\n".join(extracted)
        result["reconstruction_status"] = recon.status
        result["semantic_diagnostics"] = recon.semantic_diagnostics

        # NOTE: No WAL emission here. The caller (execution_v2.py)
        # owns case lifecycle logging via logger.end_case().
        # Emitting execution_eval from inside exec_canonical
        # would double-count as case-terminal events.

        # ── Artifact writing ─────────────────────────────────
        keep = config.execution.keep_eval_dirs
        if keep:
            artifacts = pkg_dir / "artifacts"
            artifacts.mkdir(exist_ok=True)
            (artifacts / "execution_result.json").write_text(
                json.dumps(subprocess_result, indent=2))
            (artifacts / "classified_result.json").write_text(
                json.dumps(result, indent=2))

        return result

    finally:
        # ── Cleanup ──────────────────────────────────────────
        if pkg_dir is not None:
            keep = config.execution.keep_eval_dirs
            if not keep:
                shutil.rmtree(str(pkg_dir), ignore_errors=True)
