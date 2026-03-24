"""Tests for multi-file assembly layer.

Verifies:
1. Assembly always runs for multi-file cases (no heuristic skip)
2. Duplicate definitions detected and flagged (assembly_risky)
3. Assembly provenance tracked (which files contributed)
4. Runtime errors distinguish assembly_error from logic_error
5. NameError/AttributeError during test = assembly_error, NOT logic failure
6. Single-file cases bypass assembly
7. Reference fixes pass through assembly for multi-file cases
8. assembly_error score=0.0 (not 0.2 = logic failure)

Run: .venv/bin/python -m pytest tests/test_assembly.py -v
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from exec_eval import exec_evaluate, _assemble_program

BASE = Path(__file__).resolve().parents[1]
_ALL_CASES = json.loads((BASE / "cases_v2.json").read_text())


def _get_case(case_id):
    case = next(c for c in _ALL_CASES if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        p = BASE / rel
        if p.exists():
            case["code_files_contents"][rel] = p.read_text()
    return case


# ============================================================
# Assembly function unit tests
# ============================================================

class TestAssemblyFunction:

    def test_single_file_no_assembly(self):
        case = _get_case("alias_config_a")
        asm = _assemble_program("def foo(): pass", case)
        assert not asm["assembly_used"]
        assert asm["sources"]["model_only"]

    def test_multi_file_always_assembles(self):
        """Multi-file case ALWAYS assembles — no heuristic skip."""
        case = _get_case("partial_rollback_b")
        # Even if model returns code with all definitions, assembly still runs
        all_code = "\n\n".join(case["code_files_contents"].values())
        from exec_eval import _strip_local_imports
        complete = _strip_local_imports(all_code)
        asm = _assemble_program(complete, case)
        assert asm["assembly_used"], "Multi-file must always assemble"

    def test_duplicate_defs_detected(self):
        """When model redefines a function from original, assembly_risky=True."""
        case = _get_case("partial_rollback_b")
        # Model code defines 'place_order' which exists in original
        model_code = "def place_order(): pass\ndef new_thing(): pass"
        asm = _assemble_program(model_code, case)
        assert asm["assembly_risky"], "Duplicate defs should set assembly_risky"
        assert "place_order" in asm["duplicate_defs"]

    def test_no_duplicate_defs(self):
        """Model defines only new functions: assembly_risky=False."""
        case = _get_case("partial_rollback_b")
        model_code = "def totally_new_function(): pass"
        asm = _assemble_program(model_code, case)
        assert not asm["assembly_risky"]
        assert asm["duplicate_defs"] == []

    def test_provenance_tracks_files(self):
        """Assembly sources list which original files were used."""
        case = _get_case("partial_rollback_b")
        asm = _assemble_program("x = 1", case)
        sources = asm["sources"]
        assert not sources["model_only"]
        assert len(sources["original_files"]) > 0
        assert isinstance(sources["model_defs"], list)
        assert isinstance(sources["original_defs"], list)

    def test_model_code_appended_last(self):
        """Model code comes AFTER original — its definitions override."""
        case = _get_case("partial_rollback_b")
        model_code = "def place_order(): return 'model_version'"
        asm = _assemble_program(model_code, case)
        # Model code should be at the end
        assert asm["code"].rstrip().endswith("return 'model_version'")


# ============================================================
# Runtime assembly error detection
# ============================================================

class TestAssemblyErrorDetection:

    def test_name_error_at_load_is_assembly_error(self):
        """Code referencing undefined name at module load → assembly_error."""
        case = _get_case("alias_config_a")  # single-file: no rename check
        bad_code = "x = completely_undefined_global_var\nDEFAULTS = {}"
        result = exec_evaluate(case, bad_code)
        assert not result["pass"]
        assert result["execution"]["assembly_error"]
        assert result["execution"]["status"] == "assembly_error"
        assert result["score"] == 0.0

    def test_name_error_during_test_is_assembly_error(self):
        """NameError raised DURING test execution → assembly_error."""
        case = _get_case("partial_rollback_b")
        # Code that loads fine but fails when test calls a function
        broken = """
def place_order(*a, **kw):
    return undefined_function_xyz()

def add_product(*a, **kw):
    pass

def set_gateway_fail(*a, **kw):
    pass

def available(*a, **kw):
    return 0

def get_reserved(*a, **kw):
    return 0

def get_notifications(*a, **kw):
    return []

def reset():
    pass
"""
        result = exec_evaluate(case, broken)
        assert not result["pass"]
        ex = result["execution"]
        assert ex["assembly_error"], f"NameError during test should be assembly_error, got: {result['reasons']}"
        assert result["score"] == 0.0

    def test_undefined_call_in_model_code_is_assembly_error(self):
        """Model code calls function not in any file → NameError → assembly_error."""
        case = _get_case("alias_config_a")  # single-file case
        # create_config calls an undefined function — will raise NameError when test calls it
        broken = (
            "DEFAULTS = {'timeout': 30, 'retries': 3, 'debug': False}\n"
            "def create_config(overrides=None):\n"
            "    config = nonexistent_helper_function(DEFAULTS)\n"
            "    if overrides:\n"
            "        config.update(overrides)\n"
            "    return config\n"
            "def reset_defaults():\n"
            "    pass\n"
        )
        result = exec_evaluate(case, broken)
        assert not result["pass"]
        ex = result["execution"]
        assert ex["assembly_error"], f"NameError should be assembly_error: {result['reasons']}"
        assert result["score"] == 0.0

    def test_logic_error_is_not_assembly_error(self):
        """Code that runs but produces wrong result → logic failure, NOT assembly."""
        case = _get_case("alias_config_a")
        # Buggy code that runs fine but has the wrong behavior
        buggy = case["code_files_contents"][case["code_files"][0]]
        result = exec_evaluate(case, buggy)
        assert not result["pass"]
        ex = result["execution"]
        assert not ex["assembly_error"], "Logic failure must not be assembly_error"
        assert result["score"] > 0.0  # 0.2 for logic failure


class TestAssemblyErrorScoring:

    def test_assembly_error_always_score_zero(self):
        """Assembly errors must get score=0.0 — never 0.1 or 0.2."""
        case = _get_case("partial_rollback_b")
        # Deliberately broken code
        broken = "raise NameError('missing')"
        result = exec_evaluate(case, broken)
        if result["execution"].get("assembly_error"):
            assert result["score"] == 0.0, \
                f"Assembly error should be 0.0, got {result['score']}"


# ============================================================
# Multi-file reference fix integration
# ============================================================

class TestReferenceFixAssembly:

    @pytest.mark.parametrize("case_id", [
        "partial_rollback_b", "partial_rollback_c",
        "stale_cache_b", "stale_cache_c",
        "lazy_init_b", "lazy_init_c",
        "alias_config_b", "alias_config_c",
    ])
    def test_reference_fix_passes(self, case_id):
        """Single-file reference fix + assembly with originals → passes."""
        ref_path = BASE / "reference_fixes" / f"{case_id}.py"
        if not ref_path.exists():
            pytest.skip(f"No reference fix for {case_id}")

        case = _get_case(case_id)
        ref_code = ref_path.read_text()
        result = exec_evaluate(case, ref_code)

        if len(case["code_files"]) > 1:
            assert result["execution"]["assembly_used"]

        assert result["pass"], \
            f"{case_id}: ref fix should pass. Reasons: {result.get('reasons')}"
        assert not result["execution"]["assembly_error"]


# ============================================================
# Edge cases
# ============================================================

class TestEdgeCases:

    def test_function_rename_detected(self):
        """Model renames place_order → submit_order. rename_error must be True."""
        case = _get_case("partial_rollback_b")
        # Model returns submit_order instead of place_order
        model = "def submit_order(product_id, qty, price):\n    pass"
        asm = _assemble_program(model, case)
        assert asm["assembly_used"]
        assert asm["rename_error"], \
            "Model renamed place_order to submit_order — rename_error should be True"
        assert asm["expected_func"] == "place_order"

    def test_rename_error_blocks_execution(self):
        """Renamed function → exec_evaluate returns score=0.0, does NOT run original."""
        case = _get_case("partial_rollback_b")
        model = (
            "def submit_order(product_id, qty, price):\n"
            "    # This is the model's fix, but renamed\n"
            "    return {'status': 'confirmed'}\n"
        )
        result = exec_evaluate(case, model)
        assert not result["pass"]
        assert result["score"] == 0.0
        ex = result["execution"]
        assert not ex["assembly_error"], "rename_error is a model failure, not assembly"
        assert ex.get("rename_error"), "rename_error must be True"
        assert "rename error" in result["reasons"][0].lower()

    def test_correct_override_no_rename_error(self):
        """Model defines place_order correctly → no rename_error."""
        case = _get_case("partial_rollback_b")
        ref_code = (BASE / "reference_fixes" / "partial_rollback_b.py").read_text()
        result = exec_evaluate(case, ref_code)
        assert not result["execution"].get("rename_error", False), \
            "Correct override should not trigger rename_error"

    def test_empty_model_code_still_assembles(self):
        """Empty model output + multi-file case → assembly provides original."""
        case = _get_case("partial_rollback_b")
        asm = _assemble_program("# empty", case)
        assert asm["assembly_used"]
        # Original code should be in the assembled output
        assert "reserve" in asm["code"] or "Inventory" in asm["code"]

    def test_import_stripping_consistent(self):
        """Both model code and original code have imports stripped consistently."""
        case = _get_case("partial_rollback_b")
        model_code = "from inventory import reserve\ndef place_order(): reserve('x', 1)"
        asm = _assemble_program(model_code, case)
        # 'from inventory import reserve' should be stripped from model code
        # but 'reserve' should still be available from original files
        assert "from inventory import" not in asm["code"]
