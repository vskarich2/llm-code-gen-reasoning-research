"""Spec oracle evaluation for deep dependency chain cases.

Produces two outputs:
1. patch_profiles — the invariant signature of each known fix (root_fix, trap_1..5)
   by running the spec's internal _run_chain for each patch_id
2. llm_invariants — per-invariant pass/fail from the LLM's actual code,
   by running the invariant checking functions from the spec against
   a merged module of the LLM's code

The patch_profiles are static per case family (same regardless of LLM output).
The llm_invariants depend on what the LLM produced.
Comparing llm_invariants to patch_profiles classifies the LLM's fix depth.

Only runs for DDC cases (family ends with _chain).
"""

import importlib.util
import logging
import sys
import traceback
from pathlib import Path

_log = logging.getLogger("t3.spec_oracle")

SPEC_ROOT = Path(__file__).resolve().parents[2] / "case_data" / "deep_dependency_chain_cases"


def _load_spec(case_id: str):
    """Load and return the built CaseSpec, or None for non-DDC cases."""
    family = case_id.split("_trap_")[0] if "_trap_" in case_id else case_id
    if not family.endswith("_chain"):
        return None

    case_name = family.replace("_chain", "")
    case_dir = SPEC_ROOT / case_name / "cases"
    if not case_dir.exists():
        return None

    matches = sorted(case_dir.glob("case_*.py"))
    if not matches:
        return None

    spec_path = matches[0]
    mod_name = f"_t3_spec_oracle_{case_name}"
    if mod_name in sys.modules:
        module = sys.modules[mod_name]
    else:
        try:
            spec = importlib.util.spec_from_file_location(mod_name, spec_path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[mod_name] = module
        except Exception:
            _log.debug("Failed to load spec for %s: %s", case_id, traceback.format_exc())
            return None

    build_case = getattr(module, "build_case", None)
    if build_case is None:
        return None

    try:
        return build_case()
    except Exception:
        _log.debug("build_case() failed for %s: %s", case_id, traceback.format_exc())
        return None


def _run_invariant(fn, patch_id: str) -> dict:
    """Run one invariant function, return structured result."""
    try:
        result = fn(patch_id)
        if isinstance(result, tuple) and len(result) >= 2:
            return {
                "passed": bool(result[0]),
                "message": str(result[1]),
                "tag": result[2] if len(result) > 2 else None,
            }
        return {"passed": bool(result), "message": "", "tag": None}
    except Exception as e:
        return {"passed": False, "message": f"error: {e}", "tag": None}


def build_patch_profiles(case_spec) -> dict:
    """Run invariants for each known patch_id. Returns static reference profiles."""
    profiles = {}
    patch_ids = ["root_fix", "trap_1", "trap_3", "trap_4", "trap_5"]

    for pid in patch_ids:
        profile = {}

        primary_fn = getattr(case_spec, "run_primary_test", None)
        if primary_fn:
            try:
                profile["primary_test"] = bool(primary_fn(pid))
            except Exception:
                profile["primary_test"] = False

        invariant_fns = getattr(case_spec, "run_invariant", {})
        inv_results = {}
        for name, fn in invariant_fns.items():
            inv_results[name] = _run_invariant(fn, pid)
        profile["invariants"] = inv_results
        profile["all_passed"] = all(v["passed"] for v in inv_results.values())

        classify_fn = getattr(case_spec, "classify_patch_depth", None)
        if classify_fn:
            try:
                profile["depth"] = classify_fn(pid)
            except Exception:
                profile["depth"] = "error"

        profiles[pid] = profile

    return profiles


def classify_llm_depth(exec_result: dict, patch_profiles: dict) -> dict:
    """Classify the LLM's fix depth by matching test outcome to patch profiles.

    Uses the exec_result (pass/fail + failure_reasons) to determine which
    known patch profile the LLM's output most closely matches.
    """
    llm_passed = exec_result.get("pass", False)

    # If the LLM passed all tests, it matches root_fix profile
    if llm_passed:
        return {"depth": "A", "match": "root_fix", "confidence": "test_passed"}

    # Test failed — match against trap profiles by primary_test outcome.
    # Profiles where primary_test also fails are candidates.
    # Among candidates, prefer the one with the most failed invariants
    # (more specific match = higher confidence).
    best_match = None
    best_score = -1

    for pid, profile in patch_profiles.items():
        if pid == "root_fix":
            continue
        if profile["primary_test"] == llm_passed:
            failed_invs = sum(1 for v in profile["invariants"].values() if not v["passed"])
            if failed_invs > best_score:
                best_score = failed_invs
                best_match = pid

    if best_match:
        depth = patch_profiles[best_match].get("depth", "unknown")
        return {"depth": depth, "match": best_match, "confidence": "heuristic"}

    # All trap profiles pass their primary test but LLM failed —
    # the LLM's fix is worse than any known trap
    return {"depth": "F", "match": None, "confidence": "worse_than_traps"}


def run_spec_oracle(case: dict, exec_result: dict) -> dict | None:
    """Run spec oracle for a DDC case. Returns None for non-DDC cases.

    Returns:
        {
            "status": "evaluated",
            "patch_profiles": {patch_id: {primary_test, invariants, depth, all_passed}},
            "llm_depth": {depth, match, confidence},
        }
    """
    case_id = case["id"]
    family = case_id.split("_trap_")[0] if "_trap_" in case_id else case_id
    if not family.endswith("_chain"):
        return None

    case_spec = _load_spec(case_id)
    if case_spec is None:
        return {"status": "spec_not_found", "case_id": case_id}

    try:
        profiles = build_patch_profiles(case_spec)
        llm_depth = classify_llm_depth(exec_result, profiles)

        return {
            "status": "evaluated",
            "case_id": case_id,
            "patch_profiles": profiles,
            "llm_depth": llm_depth,
        }
    except Exception as e:
        return {
            "status": "error",
            "case_id": case_id,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
