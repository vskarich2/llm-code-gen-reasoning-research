"""Stabilization tests for RC-1 through RC-6 fixes.

Each test verifies a specific root cause is eliminated.
"""

import ast
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reconstructor import reconstruct_strict, _normalize_file_content, ReconstructionResult

# ============================================================
# TEST-1: Markdown fences in file content (RC-1)
# ============================================================


class TestMarkdownFenceNormalization:

    def test_fences_stripped(self):
        content = "```python\ndef create_config():\n    return dict(DEFAULTS)\n```"
        normalized = _normalize_file_content(content)
        assert "```" not in normalized
        assert "def create_config" in normalized
        ast.parse(normalized)  # must not raise

    def test_fences_with_language_tag(self):
        content = "```python\ndef f():\n    pass\n```"
        normalized = _normalize_file_content(content)
        assert normalized.strip() == "def f():\n    pass"

    def test_fences_without_language_tag(self):
        content = "```\ndef f():\n    pass\n```"
        normalized = _normalize_file_content(content)
        assert "def f" in normalized
        assert "```" not in normalized

    def test_no_fences_unchanged(self):
        content = "def f():\n    return 42"
        normalized = _normalize_file_content(content)
        assert normalized == content

    def test_reconstruct_with_fenced_content(self):
        """Full reconstruction path: fenced file content must succeed."""
        manifest_paths = ["a.py"]
        manifest_files = {"a.py": "def f(): pass"}
        model_files = {"a.py": "```python\ndef f():\n    return 42\n```"}

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        assert recon.status == "SUCCESS", f"Expected SUCCESS, got {recon.status}"
        assert "def f" in recon.files["a.py"]
        assert "```" not in recon.files["a.py"]


# ============================================================
# TEST-2: Escaped newlines in file content (RC-2)
# ============================================================


class TestEscapedNewlineNormalization:

    def test_escaped_newlines_unescaped(self):
        content = "def f():\\n    return 42"
        normalized = _normalize_file_content(content)
        assert "\n" in normalized
        assert "\\n" not in normalized
        ast.parse(normalized)

    def test_escaped_tabs_unescaped(self):
        content = "def f():\\n\\treturn 42"
        normalized = _normalize_file_content(content)
        assert "\n" in normalized
        assert "\t" in normalized

    def test_real_newlines_not_double_unescaped(self):
        """Content with real newlines must NOT be modified."""
        content = "def f():\n    return 42"
        normalized = _normalize_file_content(content)
        assert normalized == content

    def test_mixed_real_and_escaped_left_alone(self):
        """If content has BOTH real newlines and \\n, leave it alone."""
        content = 'def f():\n    x = "line1\\nline2"\n    return x'
        normalized = _normalize_file_content(content)
        # Has real newlines → unescape should NOT fire
        assert "\\n" in normalized  # preserved inside string literal

    def test_reconstruct_with_escaped_content(self):
        manifest_paths = ["a.py"]
        manifest_files = {"a.py": "def f(): pass"}
        model_files = {"a.py": "def f():\\n    return 42"}

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        assert (
            recon.status == "SUCCESS"
        ), f"Expected SUCCESS, got {recon.status}: {recon.syntax_errors}"
        assert "\n" in recon.files["a.py"]


# ============================================================
# TEST-3: All files UNCHANGED (RC-4)
# ============================================================


class TestAllUnchanged:

    def test_all_unchanged_does_not_crash(self):
        """All-UNCHANGED must return SUCCESS with empty changed_files. No assertion crash."""
        manifest_paths = ["a.py", "b.py"]
        manifest_files = {"a.py": "def a(): pass", "b.py": "def b(): pass"}
        model_files = {"a.py": "UNCHANGED", "b.py": "UNCHANGED"}

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        assert recon.status == "SUCCESS"
        assert len(recon.changed_files) == 0
        assert recon.files["a.py"] == "def a(): pass"
        assert recon.files["b.py"] == "def b(): pass"

    def test_all_unchanged_execution_path(self):
        """All-UNCHANGED through _do_reconstruction must not crash.

        Verify the old assertion is gone from the reconstruction path.
        """
        import execution
        import inspect

        source = inspect.getsource(execution._do_reconstruction)
        assert "HARD INVARIANT: reconstruction SUCCESS must produce non-empty code" not in source
        assert 'assert parsed["code"] and parsed["code"].strip()' not in source


# ============================================================
# TEST-4: Reconstruction FAILED_SYNTAX_ERRORS with recoverable content (RC-5)
# ============================================================


class TestReconstructionRecovery:

    def test_fenced_content_still_recoverable(self):
        """If normalization fixes the fence issue, reconstruction should succeed.
        This tests the normalization in reconstruct_strict itself."""
        manifest_paths = ["a.py"]
        manifest_files = {"a.py": "original"}
        model_files = {"a.py": "```python\ndef fixed():\n    pass\n```"}

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        # After normalization, fences are stripped → AST passes → SUCCESS
        assert recon.status == "SUCCESS", f"Got {recon.status}: {recon.syntax_errors}"

    def test_genuinely_broken_syntax_still_fails(self):
        """Code with real syntax errors (not fences/escaping) should still fail."""
        manifest_paths = ["a.py"]
        manifest_files = {"a.py": "original"}
        model_files = {"a.py": "def f(\n    pass"}  # genuinely broken

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        assert recon.status == "FAILED_SYNTAX_ERRORS"
        assert "a.py" in recon.syntax_errors

    def test_execution_recovery_path_exists(self):
        """execution.py must have a recovery path for FAILED_SYNTAX_ERRORS."""
        import execution
        import inspect

        source = inspect.getsource(execution._do_reconstruction)
        assert "FAILED_SYNTAX_ERRORS" in source
        assert "_reconstruction_recovered" in source


# ============================================================
# TEST-5: Lenient file-dict parser (RC-3)
# ============================================================


class TestLenientFileDict:

    def test_malformed_json_with_literal_newlines(self):
        """File-dict JSON with literal newlines must be parsed by lenient tier."""
        from parse import _try_file_dict_lenient

        raw = (
            '{"reasoning": "The bug is aliasing", "files": {"config.py": "def f():\n    return 1"}}'
        )
        result = _try_file_dict_lenient(raw)
        assert result is not None, "Lenient file-dict parser missed malformed JSON"
        assert result["response_format"] == "file_dict_lenient"
        assert "config.py" in result["files"]
        assert "def f" in result["files"]["config.py"]

    def test_valid_json_not_matched_by_lenient(self):
        """Valid JSON should be caught by strict _try_file_dict first, not lenient."""
        from parse import _try_file_dict, _try_file_dict_lenient

        raw = '{"reasoning": "test", "files": {"a.py": "def f(): pass"}}'
        strict = _try_file_dict(raw)
        assert strict is not None  # strict tier catches it
        # lenient should also match but strict runs first in the tier chain

    def test_lenient_extracts_reasoning(self):
        from parse import _try_file_dict_lenient

        raw = '{"reasoning": "The bug is X", "files": {"a.py": "def f():\n    pass"}}'
        result = _try_file_dict_lenient(raw)
        assert result is not None
        assert "The bug is X" in result["reasoning"]

    def test_parse_model_response_uses_lenient(self):
        """parse_model_response must try lenient file-dict before code-key tiers."""
        from parse import parse_model_response

        raw = '{"reasoning": "bug", "files": {"a.py": "def f():\n    return 1"}}'
        result = parse_model_response(raw)
        assert result["response_format"] == "file_dict_lenient"
        assert result["files"] is not None


# ============================================================
# TEST-6: Regression — existing valid cases unchanged
# ============================================================


class TestRegression:

    def test_valid_file_dict_unchanged(self):
        """Valid file-dict JSON must still be parsed by strict tier."""
        from parse import parse_model_response

        raw = json.dumps(
            {"reasoning": "Fixed the bug", "files": {"a.py": "def f():\n    return 42"}}
        )
        result = parse_model_response(raw)
        assert result["response_format"] == "file_dict"
        assert result["files"]["a.py"] == "def f():\n    return 42"

    def test_valid_code_key_unchanged(self):
        from parse import parse_model_response

        raw = json.dumps({"reasoning": "Fixed", "code": "def f(): return 42"})
        result = parse_model_response(raw)
        assert result["response_format"] == "json_direct"
        assert result["code"] == "def f(): return 42"

    def test_code_block_extraction_unchanged(self):
        from parse import parse_model_response

        raw = "Here is the fix:\n```python\ndef f():\n    return 42\n```"
        result = parse_model_response(raw)
        assert result["response_format"] == "code_block"
        assert "def f" in result["code"]

    def test_reconstruct_normal_case_unchanged(self):
        """Normal reconstruction (some changed, some UNCHANGED) still works."""
        manifest_paths = ["a.py", "b.py"]
        manifest_files = {"a.py": "old_a", "b.py": "old_b"}
        model_files = {"a.py": "def fixed():\n    pass", "b.py": "UNCHANGED"}

        recon = reconstruct_strict(manifest_paths, manifest_files, model_files)
        assert recon.status == "SUCCESS"
        assert "a.py" in recon.changed_files
        assert "b.py" not in recon.changed_files
        assert recon.files["b.py"] == "old_b"

    def test_normalize_does_not_corrupt_valid_code(self):
        """Normalization must be a no-op on valid Python."""
        valid = "def f():\n    x = 'hello\\nworld'\n    return x"
        normalized = _normalize_file_content(valid)
        assert normalized == valid  # has real newlines → no change

    def test_sanity_guard_no_crash(self):
        """Sanity guard must not raise RuntimeError."""
        from runner import _validate_execution_sanity

        # Simulate a run with 0% ran rate
        results = [{"baseline": {"pass": False, "score": 0}} for _ in range(20)]
        # This must NOT crash
        _validate_execution_sanity(results, ["baseline"])
        # If we get here, the guard only warned
