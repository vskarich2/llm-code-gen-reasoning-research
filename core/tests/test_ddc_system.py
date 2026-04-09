"""Comprehensive tests for the deep dependency chain case system.

Tests cover:
  - Compiler: baseline compilation, variant compilation, comment stripping, error handling
  - Spec oracle: loading, profiles, depth classification, non-DDC handling
  - Validator: subprocess execution, buggy fails, fixed passes, idempotent
  - Pipeline integration: stage wiring, event structure
  - Case data integrity: cases_v2.json schema, code_files paths, reference fixes
  - Test files: function names match generated code, all families covered
  - Harness: run_case.py exists and is valid Python

Run: .venv/bin/python -m pytest core/tests/test_ddc_system.py -v
"""

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DATA = PROJECT_ROOT / "case_data"
DDC_ROOT = CASE_DATA / "deep_dependency_chain_cases"
CASES_V2_PATH = CASE_DATA / "cases_v2.json"

DDC_FAMILIES = [
    "auth_context_chain",
    "billing_aggregation_chain",
    "config_derivation_chain",
    "event_etl_chain",
    "logging_pipeline_chain",
    "ml_feature_chain",
    "search_index_chain",
    "serialization_pipeline_chain",
]

CASE_NAMES = [f.replace("_chain", "") for f in DDC_FAMILIES]


@pytest.fixture(scope="module")
def cases_v2():
    return json.loads(CASES_V2_PATH.read_text())


@pytest.fixture(scope="module")
def ddc_cases(cases_v2):
    families = set(DDC_FAMILIES)
    return [c for c in cases_v2 if c.get("family", c["id"]) in families]


# ============================================================
# COMPILER TESTS
# ============================================================


class TestCompilerBaseline:
    """Test baseline (non-variant) compilation."""

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_baseline_compiles(self, case_name):
        from case_data.deep_dependency_chain_cases.compiler import compile_single_case
        result = compile_single_case(case_name)
        assert result["case_name"] == case_name
        assert result["variant"] is None
        assert "data.py" in result["files"]

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_baseline_output_exists(self, case_name):
        out_dir = DDC_ROOT / case_name / "generated_cases" / case_name
        assert out_dir.exists()
        assert (out_dir / "data.py").exists()
        assert (out_dir / "pipeline.py").exists()

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_baseline_no_relative_imports(self, case_name):
        out_dir = DDC_ROOT / case_name / "generated_cases" / case_name
        for f in out_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            content = f.read_text()
            for line in content.splitlines():
                assert not line.strip().startswith("from ."), (
                    f"{case_name}/{f.name}: relative import found: {line}"
                )


class TestCompilerVariants:
    """Test variant compilation."""

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_variants_compile(self, case_name):
        from case_data.deep_dependency_chain_cases.compiler import (
            compile_single_case, _load_case_module, _extract_functions,
            _get_available_variants,
        )
        module, case_file = _load_case_module(case_name)
        extracted = _extract_functions(module, case_file)
        variants = _get_available_variants(extracted)

        assert len(variants) >= 2, f"{case_name}: expected at least 2 variants, got {variants}"

        for v in variants:
            result = compile_single_case(case_name, variant=v)
            assert result["variant"] == v
            assert result["case_name"] == case_name

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_variant_differs_from_baseline(self, case_name):
        from case_data.deep_dependency_chain_cases.compiler import (
            _load_case_module, _extract_functions, _get_available_variants,
        )
        module, case_file = _load_case_module(case_name)
        extracted = _extract_functions(module, case_file)
        variants = _get_available_variants(extracted)

        baseline_dir = DDC_ROOT / case_name / "generated_cases" / case_name
        baseline_files = {f.name: f.read_text() for f in baseline_dir.glob("*.py")
                         if f.name not in ("__init__.py", "pipeline.py", "data.py")}

        for v in variants:
            variant_dir = DDC_ROOT / case_name / "generated_cases" / f"{case_name}_{v}"
            variant_files = {f.name: f.read_text() for f in variant_dir.glob("*.py")
                             if f.name not in ("__init__.py", "pipeline.py", "data.py")}
            has_diff = any(
                variant_files.get(fname) != baseline_files.get(fname)
                for fname in set(baseline_files) | set(variant_files)
            )
            assert has_diff, f"{case_name}_{v}: all node files identical to baseline"


class TestCompilerCommentStripping:
    """All generated files must be comment-free."""

    @pytest.mark.parametrize("case_name", CASE_NAMES)
    def test_no_comments_in_generated(self, case_name):
        gen_root = DDC_ROOT / case_name / "generated_cases"
        for variant_dir in gen_root.iterdir():
            if not variant_dir.is_dir():
                continue
            for f in variant_dir.glob("*.py"):
                if f.name in ("__init__.py", "data.py", "pipeline.py"):
                    continue
                content = f.read_text()
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.lstrip()
                    assert not stripped.startswith("#"), (
                        f"{variant_dir.name}/{f.name}:{i}: comment found: {stripped[:60]}"
                    )
                    assert not stripped.startswith('"""'), (
                        f"{variant_dir.name}/{f.name}:{i}: docstring found"
                    )
                    assert not stripped.startswith("'''"), (
                        f"{variant_dir.name}/{f.name}:{i}: docstring found"
                    )


# ============================================================
# CASES_V2.JSON INTEGRITY
# ============================================================


class TestCasesV2Schema:
    """Every DDC case entry has all required fields with correct types."""

    REQUIRED_TOP = ["id", "family", "difficulty", "task", "failure_mode",
                    "code_files", "ground_truth_bug", "oracle_ground_truth",
                    "reference_fix"]

    REQUIRED_GT = ["type", "location", "invariant", "fix_pattern"]

    REQUIRED_OGT = ["bug_type", "bug_location", "mechanism_source",
                    "mechanism_property", "mechanism_steps",
                    "mechanism_outcome", "trap_description"]

    REQUIRED_RF = ["file", "function"]

    def test_all_ddc_cases_present(self, ddc_cases):
        ids = {c["id"] for c in ddc_cases}
        # 8 baselines + 30 variants = 38
        assert len(ids) == 38, f"Expected 38 DDC cases, got {len(ids)}"

    @pytest.mark.parametrize("field", REQUIRED_TOP)
    def test_top_level_fields(self, ddc_cases, field):
        for c in ddc_cases:
            assert field in c, f"{c['id']}: missing top-level field '{field}'"
            assert c[field], f"{c['id']}: empty top-level field '{field}'"

    @pytest.mark.parametrize("field", REQUIRED_GT)
    def test_ground_truth_bug_fields(self, ddc_cases, field):
        for c in ddc_cases:
            gt = c.get("ground_truth_bug", {})
            assert gt.get(field), f"{c['id']}: ground_truth_bug.{field} missing/empty"

    @pytest.mark.parametrize("field", REQUIRED_OGT)
    def test_oracle_ground_truth_fields(self, ddc_cases, field):
        for c in ddc_cases:
            ogt = c.get("oracle_ground_truth", {})
            val = ogt.get(field)
            assert val, f"{c['id']}: oracle_ground_truth.{field} missing/empty"
            if field == "mechanism_steps":
                assert isinstance(val, list) and len(val) >= 3, (
                    f"{c['id']}: mechanism_steps needs >=3 entries, got {len(val)}"
                )

    @pytest.mark.parametrize("field", REQUIRED_RF)
    def test_reference_fix_fields(self, ddc_cases, field):
        for c in ddc_cases:
            rf = c.get("reference_fix", {})
            assert rf.get(field), f"{c['id']}: reference_fix.{field} missing/empty"

    def test_code_files_exist(self, ddc_cases):
        for c in ddc_cases:
            for fp in c["code_files"]:
                full = CASE_DATA / fp
                assert full.exists(), f"{c['id']}: code_file missing: {fp}"

    def test_reference_fixes_exist(self, ddc_cases):
        for c in ddc_cases:
            ref = CASE_DATA / "reference_fixes" / f"{c['id']}.py"
            assert ref.exists(), f"{c['id']}: reference fix missing"

    def test_variant_families_point_to_baseline(self, ddc_cases):
        baseline_ids = {c["id"] for c in ddc_cases if "_trap_" not in c["id"]}
        for c in ddc_cases:
            if "_trap_" in c["id"]:
                assert c["family"] in baseline_ids, (
                    f"{c['id']}: family={c['family']!r} not a baseline case"
                )

    def test_baselines_have_no_trap(self, ddc_cases):
        for c in ddc_cases:
            if "_trap_" not in c["id"]:
                td = c["oracle_ground_truth"].get("trap_description", "")
                assert td == "No trap", f"{c['id']}: baseline has trap_description={td!r}"

    def test_variants_have_trap(self, ddc_cases):
        for c in ddc_cases:
            if "_trap_" in c["id"]:
                td = c["oracle_ground_truth"].get("trap_description", "")
                assert td != "No trap" and len(td) > 20, (
                    f"{c['id']}: variant missing trap_description"
                )

    def test_mechanism_steps_distinct(self, ddc_cases):
        seen = {}
        for c in ddc_cases:
            key = tuple(c["oracle_ground_truth"]["mechanism_steps"])
            assert key not in seen, (
                f"{c['id']} has same mechanism_steps as {seen[key]}"
            )
            seen[key] = c["id"]

    def test_task_no_buggy_function_leak(self, ddc_cases):
        for c in ddc_cases:
            task = c["task"]
            loc = c["ground_truth_bug"]["location"]
            if "::" in loc:
                fn = loc.split("::")[1]
                # Allow substring matches like "serialized" for function "serialize"
                # but not exact function name as a standalone word
                import re
                assert not re.search(rf"\b{re.escape(fn)}\b", task), (
                    f"{c['id']}: task contains buggy function name '{fn}'"
                )


# ============================================================
# TEST FILES
# ============================================================


class TestTestFiles:
    """tests_v2/ files match generated function names."""

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_test_file_exists(self, family):
        test_path = CASE_DATA / "tests_v2" / f"test_{family}.py"
        assert test_path.exists(), f"test file missing for {family}"

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_test_function_loadable(self, family):
        from core.pipeline.execution.test_loader import _load_v2_test
        case = {"family": family, "difficulty": "B"}
        fn = _load_v2_test(case)
        assert fn is not None, f"no test function found for {family}"

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_test_function_names_match_generated(self, family):
        """Functions referenced in getattr() calls must exist in generated baseline."""
        case_name = family.replace("_chain", "")
        test_path = CASE_DATA / "tests_v2" / f"test_{family}.py"
        gen_dir = DDC_ROOT / case_name / "generated_cases" / case_name

        # Extract getattr names from test file
        import re
        test_code = test_path.read_text()
        getattr_names = re.findall(r'getattr\(mod,\s*["\'](\w+)["\']', test_code)

        # Extract function/variable names from generated files
        gen_names = set()
        for f in gen_dir.glob("*.py"):
            content = f.read_text()
            gen_names.update(re.findall(r"^def (\w+)", content, re.MULTILINE))
            gen_names.update(re.findall(r"^(\w+)\s*=", content, re.MULTILINE))

        for name in getattr_names:
            assert name in gen_names, (
                f"{family}: test references '{name}' but not found in generated files. "
                f"Generated names: {sorted(gen_names)}"
            )


# ============================================================
# SPEC ORACLE
# ============================================================


class TestSpecOracle:
    """Tests for core/evaluation/spec_oracle.py."""

    def test_non_ddc_returns_none(self):
        from core.evaluation.spec_oracle import run_spec_oracle
        result = run_spec_oracle({"id": "alias_config_a"}, {"pass": True})
        assert result is None

    def test_missing_spec_returns_status(self):
        from core.evaluation.spec_oracle import run_spec_oracle
        result = run_spec_oracle({"id": "nonexistent_chain"}, {"pass": False})
        assert result is not None
        assert result["status"] == "spec_not_found"

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_spec_loads(self, family):
        from core.evaluation.spec_oracle import _load_spec
        spec = _load_spec(family)
        assert spec is not None, f"spec failed to load for {family}"
        assert hasattr(spec, "run_primary_test")
        assert hasattr(spec, "run_invariant")
        assert hasattr(spec, "classify_patch_depth")

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_profiles_have_all_patch_ids(self, family):
        from core.evaluation.spec_oracle import _load_spec, build_patch_profiles
        spec = _load_spec(family)
        profiles = build_patch_profiles(spec)
        for pid in ["root_fix", "trap_1", "trap_3", "trap_4", "trap_5"]:
            assert pid in profiles, f"{family}: missing profile for {pid}"
            assert "invariants" in profiles[pid]
            assert "depth" in profiles[pid]
            assert "primary_test" in profiles[pid]

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_five_invariants_per_profile(self, family):
        from core.evaluation.spec_oracle import _load_spec, build_patch_profiles
        spec = _load_spec(family)
        profiles = build_patch_profiles(spec)
        expected = {"trap_catching", "generalization", "causal_location",
                    "cross_path", "chain_integrity"}
        for pid, prof in profiles.items():
            actual = set(prof["invariants"].keys())
            assert actual == expected, (
                f"{family}/{pid}: invariants={actual}, expected={expected}"
            )

    def test_classify_llm_depth_passed(self):
        from core.evaluation.spec_oracle import classify_llm_depth
        result = classify_llm_depth(
            {"pass": True, "failure_reasons": []},
            {"root_fix": {"invariants": {}, "depth": "A", "primary_test": True}}
        )
        assert result["depth"] == "A"
        assert result["match"] == "root_fix"

    def test_classify_llm_depth_failed(self):
        from core.evaluation.spec_oracle import classify_llm_depth
        profiles = {
            "root_fix": {"invariants": {"a": {"passed": True}}, "depth": "A", "primary_test": True},
            "trap_1": {"invariants": {"a": {"passed": False}}, "depth": "D", "primary_test": False},
        }
        result = classify_llm_depth({"pass": False, "failure_reasons": ["err"]}, profiles)
        assert result["depth"] == "D"

    @pytest.mark.parametrize("family", DDC_FAMILIES)
    def test_variant_resolves_same_spec(self, family):
        """Trap variant cases should resolve to the same spec as the baseline."""
        from core.evaluation.spec_oracle import _load_spec
        baseline_spec = _load_spec(family)
        variant_spec = _load_spec(f"{family}_trap_4")
        assert baseline_spec is not None
        assert variant_spec is not None
        assert baseline_spec.case_id == variant_spec.case_id


# ============================================================
# PIPELINE INTEGRATION
# ============================================================


class TestPipelineWiring:
    """Verify stage_spec_oracle is properly wired into the pipeline."""

    def test_attempt_state_has_field(self):
        from core.pipeline.orchestration.attempt_state import AttemptState
        state = AttemptState()
        assert hasattr(state, "spec_oracle_result")
        assert state.spec_oracle_result is None

    def test_stage_spec_oracle_importable(self):
        from core.pipeline.orchestration.stages import stage_spec_oracle
        assert callable(stage_spec_oracle)

    def test_stage_spec_oracle_non_ddc(self):
        from core.pipeline.orchestration.attempt_state import AttemptState
        from core.pipeline.orchestration.stages import stage_spec_oracle
        state = AttemptState(exec_result={"pass": True})
        case = {"id": "alias_config_a"}
        stage_spec_oracle(state, case)
        assert state.spec_oracle_result is None

    def test_stage_spec_oracle_ddc(self):
        from core.pipeline.orchestration.attempt_state import AttemptState
        from core.pipeline.orchestration.stages import stage_spec_oracle
        state = AttemptState(exec_result={"pass": False, "failure_reasons": ["x"]})
        case = {"id": "serialization_pipeline_chain"}
        stage_spec_oracle(state, case)
        assert state.spec_oracle_result is not None
        assert state.spec_oracle_result["status"] == "evaluated"
        assert "patch_profiles" in state.spec_oracle_result
        assert "llm_depth" in state.spec_oracle_result

    def test_spec_oracle_in_event_assembly(self):
        """Verify _assemble_result_from_state includes spec_oracle in the event dict."""
        from core.config.experiment_config import load_config, is_config_loaded
        if not is_config_loaded():
            load_config("core/config/config_storage/smoke_ddc_cases.yaml")

        from core.pipeline.orchestration.execution_v2 import _assemble_result_from_state
        from core.pipeline.orchestration.attempt_state import AttemptState
        from unittest.mock import MagicMock

        state = AttemptState(
            case_id="test", condition="baseline_v3", model="test",
            exec_result={"pass": False},
            spec_oracle_result={"status": "evaluated", "test": True},
        )
        state.artifact = MagicMock()
        state.artifact.commitments_source = "none"
        state.artifact.commitment_quality_state = "none"
        state.classifier_result = MagicMock()
        state.classifier_result.parse_error = "skipped"
        state.classifier_result.reasoning_internal_consistency = None
        state.classifier_result.commitments_internal_consistency = None
        state.classifier_result.commitments_code_consistency = None
        state.classifier_result.reasoning_internal_consistency_justification = None
        state.classifier_result.commitments_internal_consistency_justification = None
        state.classifier_result.commitments_code_consistency_justification = None
        state.classifier_result.reasoning_code_alignment_justification = None
        state.classifier_result.commitment_source_for_classifier = None
        state.signals = MagicMock()
        state.signals.v2_category = "test"
        state.signals.legacy_compat_category = "test"
        state.recon = MagicMock()
        state.recon.status = "SUCCESS"
        state.recon.changed_files = set()
        state.recon.files = {}
        state.recon.syntax_errors = {}
        state.recon.missing_files = set()
        state.recon.semantic_diagnostics = {}
        state.routing = MagicMock()
        state.routing.selected_source = "strict"
        state.evaluation = {}
        state.artifact_id = "test_id"
        state.ast_result = MagicMock()
        state.ast_result.to_dict = lambda: {"status": "no_spec"}
        state.oracle_result = {}
        state.disagreement = {}
        state.strict_parse = MagicMock()
        state.strict_parse.parse_valid = True
        state.strict_parse.schema_valid = True
        state.strict_parse.parse_error = None
        state.strict_parse.possible_mis_extraction = False
        state.format_parse = MagicMock()
        state.format_parse.format_valid = True
        state.format_parse.format_error = None
        state.recovery_parse = MagicMock()
        state.recovery_parse.parse_valid = True
        state.recovery_parse.schema_valid = True
        state.recovery_parse.recovery_type = None
        state.recovery_parse.recovery_steps = []
        state.recovery_parse.execution_equivalent = True
        state.recovery_parse.schema_normalization_applied = False
        state.prompt_meta = {"template": "test"}
        state.parsed_gen = MagicMock()
        state.parsed_gen.parse_valid = True
        state.parsed_gen.parse_status = "success"

        case = {"id": "test", "family": "test", "difficulty": "B",
                "code_files": [], "failure_mode": "LOGIC"}

        ev = _assemble_result_from_state(state, case)
        assert "spec_oracle" in ev
        assert ev["spec_oracle"]["status"] == "evaluated"
        assert ev["spec_oracle"]["test"] is True

    def test_spec_oracle_absent_for_non_ddc(self):
        """Verify spec_oracle is NOT in event when result is None."""
        from core.config.experiment_config import load_config, is_config_loaded
        if not is_config_loaded():
            load_config("core/config/config_storage/smoke_ddc_cases.yaml")

        from core.pipeline.orchestration.execution_v2 import _assemble_result_from_state
        from core.pipeline.orchestration.attempt_state import AttemptState
        from unittest.mock import MagicMock

        state = AttemptState(
            case_id="test", condition="baseline_v3", model="test",
            exec_result={"pass": True},
            spec_oracle_result=None,
        )
        state.artifact = MagicMock()
        state.artifact.commitments_source = "none"
        state.artifact.commitment_quality_state = "none"
        state.classifier_result = MagicMock()
        state.classifier_result.parse_error = "skipped"
        state.classifier_result.reasoning_internal_consistency = None
        state.classifier_result.commitments_internal_consistency = None
        state.classifier_result.commitments_code_consistency = None
        state.classifier_result.reasoning_internal_consistency_justification = None
        state.classifier_result.commitments_internal_consistency_justification = None
        state.classifier_result.commitments_code_consistency_justification = None
        state.classifier_result.reasoning_code_alignment_justification = None
        state.classifier_result.commitment_source_for_classifier = None
        state.signals = MagicMock()
        state.signals.v2_category = "test"
        state.signals.legacy_compat_category = "test"
        state.recon = MagicMock()
        state.recon.status = "SUCCESS"
        state.recon.changed_files = set()
        state.recon.files = {}
        state.recon.syntax_errors = {}
        state.recon.missing_files = set()
        state.recon.semantic_diagnostics = {}
        state.routing = MagicMock()
        state.routing.selected_source = "strict"
        state.evaluation = {}
        state.artifact_id = "test_id"
        state.ast_result = MagicMock()
        state.ast_result.to_dict = lambda: {"status": "no_spec"}
        state.oracle_result = {}
        state.disagreement = {}
        state.strict_parse = MagicMock()
        state.strict_parse.parse_valid = True
        state.strict_parse.schema_valid = True
        state.strict_parse.parse_error = None
        state.strict_parse.possible_mis_extraction = False
        state.format_parse = MagicMock()
        state.format_parse.format_valid = True
        state.format_parse.format_error = None
        state.recovery_parse = MagicMock()
        state.recovery_parse.parse_valid = True
        state.recovery_parse.schema_valid = True
        state.recovery_parse.recovery_type = None
        state.recovery_parse.recovery_steps = []
        state.recovery_parse.execution_equivalent = True
        state.recovery_parse.schema_normalization_applied = False
        state.prompt_meta = {"template": "test"}
        state.parsed_gen = MagicMock()
        state.parsed_gen.parse_valid = True
        state.parsed_gen.parse_status = "success"

        case = {"id": "test", "family": "test", "difficulty": "B",
                "code_files": [], "failure_mode": "LOGIC"}

        ev = _assemble_result_from_state(state, case)
        assert "spec_oracle" not in ev


# ============================================================
# HARNESS
# ============================================================


class TestHarness:
    """run_case.py exists and is valid Python."""

    def test_run_case_exists(self):
        from core.config.paths import HARNESS_SCRIPT
        assert HARNESS_SCRIPT.exists(), f"run_case.py not found at {HARNESS_SCRIPT}"

    def test_run_case_valid_python(self):
        from core.config.paths import HARNESS_SCRIPT
        import ast
        code = HARNESS_SCRIPT.read_text()
        ast.parse(code)  # raises SyntaxError if invalid

    def test_run_case_has_main(self):
        from core.config.paths import HARNESS_SCRIPT
        code = HARNESS_SCRIPT.read_text()
        assert "def main():" in code
        assert '__name__ == "__main__"' in code


# ============================================================
# VALIDATOR (subprocess-based)
# ============================================================


class TestValidator:
    """Tests for validate_cases_v2.py using subprocess execution."""

    def test_read_case_files(self, ddc_cases):
        from core.pipeline.orchestration.validate_cases_v2 import _read_case_files
        for c in ddc_cases[:3]:
            files = _read_case_files(c)
            assert len(files) >= 3, f"{c['id']}: only {len(files)} files"
            assert "data.py" in files

    def test_baseline_buggy_fails(self, cases_v2):
        """Buggy baseline code must fail the test (via subprocess)."""
        from core.pipeline.orchestration.validate_cases_v2 import (
            _read_case_files, _run_case,
        )
        c = next(c for c in cases_v2 if c["id"] == "serialization_pipeline_chain")
        files = _read_case_files(c)
        result = _run_case(c, files)
        assert result.get("status") == "ok"
        assert result.get("passed") is False

    def test_baseline_fixed_passes(self, cases_v2):
        """Reference fix must pass the test (via subprocess)."""
        from core.pipeline.orchestration.validate_cases_v2 import (
            _read_case_files, _read_baseline_files, _run_case,
        )
        from core.config.paths import REFERENCE_FIXES_DIR
        c = next(c for c in cases_v2 if c["id"] == "serialization_pipeline_chain")
        files = _read_baseline_files(c)
        ref_code = (REFERENCE_FIXES_DIR / f"{c['id']}.py").read_text()
        bug_file = c["reference_fix"]["file"]
        files[bug_file] = ref_code
        result = _run_case(c, files)
        assert result.get("status") == "ok"
        assert result.get("passed") is True

    def test_variant_buggy_fails(self, cases_v2):
        """Trap variant code must fail the test."""
        from core.pipeline.orchestration.validate_cases_v2 import (
            _read_case_files, _run_case,
        )
        c = next(c for c in cases_v2 if c["id"] == "serialization_pipeline_chain_trap_4")
        files = _read_case_files(c)
        result = _run_case(c, files)
        assert result.get("status") == "ok"
        assert result.get("passed") is False

    def test_read_baseline_files_for_variant(self, cases_v2):
        """_read_baseline_files for a variant should return the baseline's files."""
        from core.pipeline.orchestration.validate_cases_v2 import (
            _read_case_files, _read_baseline_files,
        )
        baseline = next(c for c in cases_v2 if c["id"] == "auth_context_chain")
        variant = next(c for c in cases_v2 if c["id"] == "auth_context_chain_trap_4")

        baseline_files = _read_case_files(baseline)
        variant_baseline_files = _read_baseline_files(variant)

        assert baseline_files == variant_baseline_files
