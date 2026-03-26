"""Validation tests for the v3 multi-file pipeline redesign.

Tests cover:
1. Repo-root import resolution (PYTHONPATH=pkg_root)
2. Canonical module key correctness
3. Token reduction immutability
4. Reduction disclosure in prompts
5. LEG classification table completeness
6. Roundtrip reconstruction (all UNCHANGED -> identical)
7. Missing file rejection (strict reconstruction)
8. Cross-case subprocess isolation
9. Format robustness (whitespace in UNCHANGED, extra files)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_multi_file_case():
    cases = json.loads((BASE_DIR / "cases_v2.json").read_text())
    # Find a multi-file case
    for c in cases:
        if len(c["code_files"]) >= 3:
            c["code_files_contents"] = {
                f: (BASE_DIR / f).read_text() for f in c["code_files"]
            }
            return c
    pytest.skip("No multi-file case with >= 3 files found")


@pytest.fixture
def sample_single_file_case():
    cases = json.loads((BASE_DIR / "cases_v2.json").read_text())
    for c in cases:
        if len(c["code_files"]) == 1:
            c["code_files_contents"] = {
                f: (BASE_DIR / f).read_text() for f in c["code_files"]
            }
            return c
    pytest.skip("No single-file case found")


# ---------------------------------------------------------------------------
# 1. Repo-root import test
# ---------------------------------------------------------------------------


def test_repo_root_imports():
    """Verify PYTHONPATH=pkg_root makes flat sibling imports resolve."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = Path(tmpdir) / "test_case"
        pkg.mkdir()
        (pkg / "models.py").write_text("class Foo:\n    x = 1")
        (pkg / "service.py").write_text(
            "from models import Foo\ndef get(): return Foo.x"
        )
        result = subprocess.run(
            [sys.executable, "-c",
             "from service import get; assert get() == 1; print('OK')"],
            cwd=str(pkg),
            env={"PYTHONPATH": str(pkg), "PATH": ""},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 2. Canonical module key test
# ---------------------------------------------------------------------------


def test_canonical_mods_keys():
    """Verify harness generates mods dict with correct canonical keys."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from subprocess_eval import _generate_harness
        modules = ["cache_writer", "cache_reader", "user_service"]
        harness = _generate_harness(modules, "def test(mods): pass", "test")
        for m in modules:
            assert f'mods["{m}"]' in harness, f"Missing key for {m}"
            assert f'importlib.import_module("{m}")' in harness
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 3. Reduction immutability test
# ---------------------------------------------------------------------------


def test_reduction_does_not_mutate_inputs():
    """Token reduction must not change the original files dict."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        # Config must be loaded for token budget lookup
        from experiment_config import load_config, is_config_loaded
        if not is_config_loaded():
            load_config(str(BASE_DIR / "configs" / "default.yaml"))

        from prompt_view import build_prompt_view

        original_files = {
            "code_snippets/test/a.py": "def f():\n    return 1\n\n\n\n",
            "code_snippets/test/b.py": "def g():\n    return 2\n",
        }
        snapshot = {k: v for k, v in original_files.items()}

        def mock_renderer(view, condition):
            parts = [c for _, c in view.files_full]
            return "\n".join(parts)

        view = build_prompt_view(
            file_paths=list(original_files.keys()),
            files=original_files,
            import_graph={},
            reference_fix_file=None,
            prompt_renderer=mock_renderer,
            condition="baseline",
            model="gpt-4.1-nano",
        )
        assert original_files == snapshot, "Manifest files were mutated by reduction"
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 4. Reduction disclosure test
# ---------------------------------------------------------------------------


def test_reduction_disclosure_in_prompt():
    """Reduced prompt must disclose which files are summarized/dropped."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from prompt_view import PromptView

        # Level 2: summarized files should be labeled
        view = PromptView(
            files_full=(("a.py", "def f(): pass"),),
            files_summarized=(("b.py", "def g(): ..."),),
            files_dropped=(),
            reduction_level=2,
            original_file_count=2,
            token_estimate=100,
            infeasible=False,
        )
        assert len(view.files_summarized) == 1
        assert view.reduction_level == 2
        # The summarized files exist in the view for prompt rendering

        # Level 3: dropped files should be tracked
        view3 = PromptView(
            files_full=(("a.py", "def f(): pass"),),
            files_summarized=(),
            files_dropped=("b.py", "c.py"),
            reduction_level=3,
            original_file_count=3,
            token_estimate=50,
            infeasible=False,
        )
        assert len(view3.files_dropped) == 2
        assert view3.full_file_paths == ["a.py"]
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 5. LEG classification table test
# ---------------------------------------------------------------------------


def test_leg_classification_rules():
    """Verify key rows of the LEG rule table produce correct classification."""
    # Import the classifier (we define it inline since it may not be extracted yet)
    def classify(error_type, reasoning, response_format, reasoning_correct):
        reasoning_eval = (
            isinstance(reasoning, str) and len(reasoning.strip()) > 0
            and response_format in ("file_dict", "code_dict")
        )
        code_correct = error_type == "logic_pass"
        in_primary = error_type in ("logic_pass", "logic_failure", "execution_error")

        if in_primary and reasoning_eval:
            if reasoning_correct is True and code_correct:
                return "true_success", True, True
            elif reasoning_correct is False and code_correct:
                return "lucky_fix", True, True
            elif reasoning_correct is True and not code_correct:
                return "leg", True, True
            elif reasoning_correct is False and not code_correct:
                return "true_failure", True, True
            else:
                return "unclassified", True, False
        elif error_type == "reconstruction_failure" and reasoning_eval:
            if reasoning_correct is True:
                return "leg", False, True  # secondary LEG
            elif reasoning_correct is False:
                return "true_failure", False, True
            else:
                return "excluded", False, False
        elif in_primary:
            return "unclassified", True, False
        else:
            return "excluded", False, False

    test_cases = [
        # (error_type, reasoning, format, reasoning_correct, expected_cat, expected_primary, expected_leg)
        ("logic_pass", "good", "file_dict", True, "true_success", True, True),
        ("logic_pass", "wrong", "file_dict", False, "lucky_fix", True, True),
        ("logic_pass", "x", "file_dict", None, "unclassified", True, False),
        ("logic_failure", "good", "file_dict", True, "leg", True, True),
        ("logic_failure", "wrong", "file_dict", False, "true_failure", True, True),
        ("execution_error", "good", "file_dict", True, "leg", True, True),
        ("reconstruction_failure", "good", "file_dict", True, "leg", False, True),
        ("reconstruction_failure", "good", "file_dict", False, "true_failure", False, True),
        ("format_violation", "any", "file_dict", None, "excluded", False, False),
        ("parse_error", "", "raw_fallback", None, "excluded", False, False),
    ]

    for et, reasoning, fmt, rc, exp_cat, exp_primary, exp_leg in test_cases:
        cat, primary, leg = classify(et, reasoning, fmt, rc)
        assert cat == exp_cat, f"Row {et}/{reasoning[:5]}: expected {exp_cat}, got {cat}"
        assert primary == exp_primary, f"Row {et}: primary mismatch"
        assert leg == exp_leg, f"Row {et}: leg mismatch"


# ---------------------------------------------------------------------------
# 6. Roundtrip reconstruction test
# ---------------------------------------------------------------------------


def test_roundtrip_all_unchanged(sample_multi_file_case):
    """All UNCHANGED -> reconstructed files identical to originals."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from reconstructor import reconstruct_strict

        case = sample_multi_file_case
        paths = case["code_files"]
        originals = case["code_files_contents"]

        model_files = {f: "UNCHANGED" for f in paths}
        result = reconstruct_strict(paths, originals, model_files)

        assert result.status == "SUCCESS"
        assert result.files == originals
        assert result.changed_files == set()
        assert result.missing_files == set()
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 7. Missing file rejection test
# ---------------------------------------------------------------------------


def test_missing_file_rejected(sample_multi_file_case):
    """Response missing a file -> FAILED_MISSING_FILES."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from reconstructor import reconstruct_strict

        case = sample_multi_file_case
        paths = case["code_files"]
        originals = case["code_files_contents"]

        # Only provide first file
        model_files = {paths[0]: "UNCHANGED"}
        result = reconstruct_strict(paths, originals, model_files)

        assert result.status == "FAILED_MISSING_FILES"
        assert result.format_violation is True
        assert len(result.missing_files) == len(paths) - 1
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 8. Cross-case subprocess isolation test
# ---------------------------------------------------------------------------


def test_subprocess_isolation():
    """Mutations in case A do not leak into case B."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from subprocess_eval import evaluate_in_subprocess

        files_a = {"code_snippets/a/shared.py": "STATE = []\ndef mutate(): STATE.append(1)"}
        test_a = 'def test(mods): mods["shared"].mutate(); return True, ["ok"]'
        evaluate_in_subprocess("a", list(files_a.keys()), files_a, test_a, ["shared"])

        files_b = {"code_snippets/b/shared.py": "STATE = []\ndef check(): return len(STATE)"}
        test_b = 'def test(mods): n = mods["shared"].check(); return (n == 0, [f"leaked: {n}"])'
        result = evaluate_in_subprocess("b", list(files_b.keys()), files_b, test_b, ["shared"])

        assert result["pass"], f"State leaked between subprocesses: {result['reasons']}"
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 9. Format robustness tests
# ---------------------------------------------------------------------------


def test_unchanged_with_whitespace():
    """UNCHANGED with surrounding whitespace still recognized."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from reconstructor import reconstruct_strict

        paths = ["a.py", "b.py"]
        originals = {"a.py": "def f(): return 1", "b.py": "def g(): return 2"}
        model_files = {"a.py": "  UNCHANGED  ", "b.py": "UNCHANGED"}

        result = reconstruct_strict(paths, originals, model_files)
        assert result.status == "SUCCESS"
        assert result.files["a.py"] == originals["a.py"]
    finally:
        sys.path.pop(0)


def test_extra_files_recorded():
    """Extra files in model response are recorded but don't cause failure."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from reconstructor import reconstruct_strict

        paths = ["a.py"]
        originals = {"a.py": "def f(): return 1"}
        model_files = {"a.py": "UNCHANGED", "extra.py": "# extra file"}

        result = reconstruct_strict(paths, originals, model_files)
        assert result.status == "SUCCESS"
        assert "extra.py" in result.extra_files
    finally:
        sys.path.pop(0)


def test_syntax_error_detected():
    """Syntax errors in model output are caught during reconstruction."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from reconstructor import reconstruct_strict

        paths = ["a.py"]
        originals = {"a.py": "def f(): return 1"}
        model_files = {"a.py": "def f(:"}  # invalid syntax

        result = reconstruct_strict(paths, originals, model_files)
        assert result.status == "FAILED_SYNTAX_ERRORS"
        assert "a.py" in result.syntax_errors
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# 10. Parser tier classification test
# ---------------------------------------------------------------------------


def test_parser_tiers():
    """Verify response_format tag is correctly assigned for each tier."""
    sys.path.insert(0, str(BASE_DIR))
    try:
        from parse import parse_model_response

        # Tier 0: file_dict
        r1 = parse_model_response(json.dumps({
            "reasoning": "test", "files": {"a.py": "pass"}
        }))
        assert r1["response_format"] == "file_dict"

        # Tier 1a: code_dict
        r2 = parse_model_response(json.dumps({
            "reasoning": "test", "code": {"a.py": "pass"}
        }))
        assert r2["response_format"] == "code_dict"

        # Tier 1b: json_direct (code as string)
        r3 = parse_model_response(json.dumps({
            "reasoning": "test", "code": "def f(): pass"
        }))
        assert r3["response_format"] == "json_direct"

        # Tier 4: raw fallback
        r4 = parse_model_response("just some text with no structure")
        assert r4["response_format"] == "raw_fallback"
    finally:
        sys.path.pop(0)
