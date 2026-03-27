"""Component Contract Tests + Failure Mode Tests.

Verifies each component's input/output contract and that failure modes
produce explicit, correct behavior.
"""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from parse import parse_model_response
from reconstructor import reconstruct_strict
from exec_eval import exec_evaluate


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


# ============================================================
# PARSER CONTRACTS
# ============================================================


class TestParserContracts:

    def test_file_dict_sets_code_none(self):
        raw = json.dumps({"reasoning": "x", "files": {"a.py": "pass"}})
        result = parse_model_response(raw)
        assert result["response_format"] == "file_dict"
        assert result["code"] is None
        assert isinstance(result["files"], dict)

    def test_json_direct_sets_code_string(self):
        raw = json.dumps({"reasoning": "x", "code": "def f(): pass"})
        result = parse_model_response(raw)
        assert result["response_format"] == "json_direct"
        assert isinstance(result["code"], str)
        assert result["code"].strip() != ""

    def test_empty_response_marked_severe(self):
        result = parse_model_response("")
        assert result["parse_error"] is not None
        assert "SEVERE" in result["parse_error"]

    def test_invalid_json_falls_to_raw(self):
        result = parse_model_response("{invalid json here")
        assert result["response_format"] == "raw_fallback"
        assert result.get("_raw_fallback") is True


# ============================================================
# RECONSTRUCTOR CONTRACTS
# ============================================================


class TestReconstructorContracts:

    def test_success_has_all_files(self):
        paths = ["a.py", "b.py"]
        originals = {"a.py": "x = 1", "b.py": "y = 2"}
        model = {"a.py": "x = 42", "b.py": "UNCHANGED"}
        result = reconstruct_strict(paths, originals, model)
        assert result.status == "SUCCESS"
        assert set(result.files.keys()) == set(paths)

    def test_changed_files_only_modified(self):
        paths = ["a.py", "b.py"]
        originals = {"a.py": "x = 1", "b.py": "y = 2"}
        model = {"a.py": "x = 42", "b.py": "UNCHANGED"}
        result = reconstruct_strict(paths, originals, model)
        assert result.changed_files == {"a.py"}

    def test_unchanged_resolved_to_original(self):
        paths = ["a.py", "b.py"]
        originals = {"a.py": "x = 1", "b.py": "y = 2"}
        model = {"a.py": "x = 42", "b.py": "UNCHANGED"}
        result = reconstruct_strict(paths, originals, model)
        assert result.files["b.py"] == "y = 2"

    def test_missing_file_fails(self):
        result = reconstruct_strict(
            ["a.py", "b.py"],
            {"a.py": "x", "b.py": "y"},
            {"a.py": "x"},
        )
        assert result.status == "FAILED_MISSING_FILES"
        assert "b.py" in result.missing_files

    def test_empty_content_fails(self):
        result = reconstruct_strict(["a.py"], {"a.py": "x = 1"}, {"a.py": ""})
        assert result.status == "FAILED_EMPTY_FILES"

    def test_syntax_error_detected(self):
        result = reconstruct_strict(["a.py"], {"a.py": "x = 1"}, {"a.py": "def f(:"})
        assert result.status == "FAILED_SYNTAX_ERRORS"
        assert "a.py" in result.syntax_errors


# ============================================================
# EVALUATOR CONTRACTS
# ============================================================


class TestEvaluatorContracts:

    def test_none_code_not_run(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, None)
        assert result["pass"] is False
        assert result["execution"]["ran"] is False

    def test_empty_code_not_run(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "")
        assert result["pass"] is False
        assert result["execution"]["ran"] is False

    def test_short_code_not_run(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "x = 1")
        assert result["execution"]["ran"] is False

    def test_syntax_error_reported(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "def f(:\n    pass\n" * 5)
        assert result["pass"] is False
        assert result["execution"].get("syntax_error") is not None
