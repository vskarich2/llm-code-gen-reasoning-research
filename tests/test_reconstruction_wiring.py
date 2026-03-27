"""L2: Integration Tests — Reconstruction Wiring.

Tests the FULL pipeline: file_dict → reconstruct → wire → exec_evaluate.
Includes equivalence-against-oracle, behavioral tests, real response fixtures,
and both code paths (baseline file_dict + leg_reduction flat string).
"""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from parse import parse_model_response
from reconstructor import reconstruct_strict
from exec_eval import exec_evaluate, load_module_from_code, _load_v2_test, _assemble_program
from validate_cases_v2 import load_reference_code, load_case_code


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


def _simulate_file_dict_pipeline(case, code_content):
    """Simulate the full file_dict pipeline:
    parse → reconstruct → wire changed-files-only → return code string.

    code_content: the code to put in the file_dict for the bug file.
    """
    bug_file = case.get("reference_fix", {}).get("file", case["code_files"][0])
    files_dict = {}
    for f in case["code_files"]:
        if f == bug_file:
            files_dict[f] = code_content
        else:
            files_dict[f] = "UNCHANGED"

    raw = json.dumps({"reasoning": "test", "files": files_dict})
    parsed = parse_model_response(raw)

    assert parsed["response_format"] == "file_dict"
    assert parsed["code"] is None  # Parser sets None for file_dict
    assert parsed["files"] is not None

    manifest = case["code_files_contents"]
    manifest_paths = list(manifest.keys())
    recon = reconstruct_strict(manifest_paths, manifest, parsed["files"])

    if recon.status != "SUCCESS":
        return None, recon

    # Wire changed-files-only (same logic as execution.py)
    changed_parts = [recon.files[p] for p in manifest_paths if p in recon.changed_files]
    code = "\n\n".join(changed_parts) if changed_parts else ""
    return code, recon


# ============================================================
# BEHAVIORAL: reference fix through file_dict pipeline must PASS
# ============================================================


class TestFileDict:

    def test_single_file_reference_fix_passes(self):
        """alias_config_a (single file): file_dict with ref fix → pass=True."""
        case = _load_case("alias_config_a")
        ref_code = (BASE / "reference_fixes" / "alias_config_a.py").read_text()
        code, recon = _simulate_file_dict_pipeline(case, ref_code)
        assert recon.status == "SUCCESS"
        assert code and code.strip(), "Wired code is empty after reconstruction"
        result = exec_evaluate(case, code)
        assert result["execution"]["ran"] is True, f"Code did not run: {result}"
        assert result["pass"] is True, f"Reference fix failed: {result.get('reasons')}"

    def test_multi_file_reference_fix_passes(self):
        """alias_config_b (2 files): file_dict with ref fix → pass=True."""
        case = _load_case("alias_config_b")
        ref_code = (BASE / "reference_fixes" / "alias_config_b.py").read_text()
        code, recon = _simulate_file_dict_pipeline(case, ref_code)
        assert recon.status == "SUCCESS"
        assert code and code.strip()
        result = exec_evaluate(case, code)
        assert result["execution"]["ran"] is True, f"Code did not run: {result}"
        assert result["pass"] is True, f"Multi-file ref fix failed: {result.get('reasons')}"

    def test_buggy_code_runs_but_fails(self):
        """Buggy code through file_dict pipeline → ran=True, pass=False.
        This is THE test that catches the original wiring bug — if ran=False,
        the pipeline is broken."""
        case = _load_case("alias_config_a")
        buggy_code = case["code_files_contents"][case["code_files"][0]]
        code, recon = _simulate_file_dict_pipeline(case, buggy_code)
        assert recon.status == "SUCCESS"
        assert code and code.strip()
        result = exec_evaluate(case, code)
        assert result["execution"]["ran"] is True, (
            f"PIPELINE BROKEN: buggy code did not run (ran=False). "
            f"This is the exact symptom of the reconstruction wiring bug. "
            f"Result: {result}"
        )
        assert result["pass"] is False

    def test_multi_file_changed_only_in_code(self):
        """Only changed files appear in wired code, not UNCHANGED files."""
        case = _load_case("alias_config_b")
        ref_code = (BASE / "reference_fixes" / "alias_config_b.py").read_text()
        code, recon = _simulate_file_dict_pipeline(case, ref_code)
        assert recon.status == "SUCCESS"
        # The unchanged file's content should NOT be in the wired code
        unchanged_file = [f for f in case["code_files"] if f != case["reference_fix"]["file"]][0]
        unchanged_content = case["code_files_contents"][unchanged_file]
        # Check a distinctive line from the unchanged file
        first_func = (
            [l for l in unchanged_content.splitlines() if l.startswith("def ")][0]
            if any(l.startswith("def ") for l in unchanged_content.splitlines())
            else None
        )
        if first_func:
            assert first_func not in code, (
                f"Unchanged file content found in wired code — "
                f"should only contain changed files"
            )


# ============================================================
# EQUIVALENCE-AGAINST-ORACLE
# ============================================================


class TestEquivalenceAgainstOracle:
    """Compare changed-files-only path against direct reference fix (oracle)."""

    @pytest.mark.parametrize(
        "case_id",
        [
            "alias_config_a",
            "alias_config_b",
            "stale_cache_a",
            "partial_update_a",
            "mutable_default_a",
        ],
    )
    def test_reconstruction_matches_oracle(self, case_id):
        case = _load_case(case_id)
        ref_code_direct = load_reference_code(case)

        # Oracle: reference fix directly through exec_evaluate
        oracle_result = exec_evaluate(case, ref_code_direct)
        assert oracle_result["pass"] is True, f"Oracle failed for {case_id}"

        # Path B: file_dict → reconstruct → changed-files-only
        ref_file_code = (BASE / "reference_fixes" / f"{case_id}.py").read_text()
        code_b, recon = _simulate_file_dict_pipeline(case, ref_file_code)
        assert recon.status == "SUCCESS"
        result_b = exec_evaluate(case, code_b)

        # Must agree
        assert result_b["pass"] == oracle_result["pass"], (
            f"EQUIVALENCE FAILURE for {case_id}: "
            f"oracle pass={oracle_result['pass']}, pipeline pass={result_b['pass']}. "
            f"Pipeline reasons: {result_b.get('reasons')}"
        )


# ============================================================
# REAL RESPONSE FIXTURES
# ============================================================


class TestRealResponseFixtures:
    """Parse actual model responses through the real pipeline."""

    @pytest.fixture
    def fixtures(self):
        fx_path = BASE / "tests" / "fixtures" / "real_responses.json"
        return json.loads(fx_path.read_text())

    def test_baseline_fixture_parses(self, fixtures):
        """Real baseline response parses as file_dict."""
        fx = next(
            f for f in fixtures if f["condition"] == "baseline" and f["case_id"] == "alias_config_a"
        )
        parsed = parse_model_response(fx["raw_response"])
        assert parsed["response_format"] in (
            "file_dict",
            "code_dict",
            "json_direct",
        ), f"Unexpected format: {parsed['response_format']}"

    def test_leg_reduction_fixture_parses(self, fixtures):
        """Real leg_reduction response parses with code field."""
        fx = next(f for f in fixtures if f["condition"] == "leg_reduction")
        from leg_reduction import parse_leg_reduction_output

        lr_parsed = parse_leg_reduction_output(fx["raw_response"])
        assert lr_parsed["code"] is not None
        assert isinstance(lr_parsed["code"], str)
        assert len(lr_parsed["code"].strip()) > 10

    def test_baseline_fixture_executes(self, fixtures):
        """Real baseline response through reconstruction → ran=True."""
        fx = next(
            f for f in fixtures if f["condition"] == "baseline" and f["case_id"] == "alias_config_a"
        )
        case = _load_case("alias_config_a")
        parsed = parse_model_response(fx["raw_response"])

        if parsed.get("files"):
            manifest = case["code_files_contents"]
            manifest_paths = list(manifest.keys())
            recon = reconstruct_strict(manifest_paths, manifest, parsed["files"])
            if recon.status == "SUCCESS":
                changed = [recon.files[p] for p in manifest_paths if p in recon.changed_files]
                code = "\n\n".join(changed)
            else:
                code = parsed.get("code", "")
        else:
            code = parsed.get("code", "")

        result = exec_evaluate(case, code)
        assert (
            result["execution"]["ran"] is True
        ), f"Real baseline fixture did not run: {result.get('reasons')}"

    def test_leg_reduction_fixture_executes(self, fixtures):
        """Real leg_reduction response → ran=True."""
        fx = next(f for f in fixtures if f["condition"] == "leg_reduction")
        case = _load_case("alias_config_a")
        from leg_reduction import parse_leg_reduction_output

        lr_parsed = parse_leg_reduction_output(fx["raw_response"])
        result = exec_evaluate(case, lr_parsed["code"])
        assert (
            result["execution"]["ran"] is True
        ), f"Real leg_reduction fixture did not run: {result.get('reasons')}"


# ============================================================
# BOTH CODE PATHS EXECUTE
# ============================================================


class TestBothPathsExecute:
    """Baseline (file_dict) and leg_reduction (flat string) both produce executable code."""

    def test_same_ref_fix_both_paths_pass(self):
        """Same reference fix code through both paths → both pass=True."""
        case = _load_case("alias_config_a")
        ref_code = (BASE / "reference_fixes" / "alias_config_a.py").read_text()

        # Baseline path: file_dict → reconstruct → exec_evaluate
        code_bl, recon = _simulate_file_dict_pipeline(case, ref_code)
        result_bl = exec_evaluate(case, code_bl)

        # leg_reduction path: direct code string → exec_evaluate
        result_lr = exec_evaluate(case, ref_code)

        assert result_bl["pass"] is True, f"Baseline path failed: {result_bl.get('reasons')}"
        assert result_lr["pass"] is True, f"leg_reduction path failed: {result_lr.get('reasons')}"


# ============================================================
# RECONSTRUCTION FAILURE HANDLING
# ============================================================


class TestReconstructionFailures:

    def test_missing_file_graceful(self):
        """Missing file in file_dict → reconstruction fails → code stays empty."""
        case = _load_case("alias_config_b")
        # Only provide 1 of 2 files
        bug_file = case["reference_fix"]["file"]
        raw = json.dumps({"reasoning": "test", "files": {bug_file: "pass"}})
        parsed = parse_model_response(raw)
        manifest = case["code_files_contents"]
        manifest_paths = list(manifest.keys())
        recon = reconstruct_strict(manifest_paths, manifest, parsed["files"])
        assert recon.status == "FAILED_MISSING_FILES"

    def test_empty_code_not_run(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "")
        assert result["pass"] is False
        assert result["execution"]["ran"] is False
