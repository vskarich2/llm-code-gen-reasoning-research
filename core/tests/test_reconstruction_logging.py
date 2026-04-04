"""Tests for reconstruction result logging completeness.

Verifies that ALL ReconstructionResult fields flow into the event
reconstruction section, and that recovery types are correctly tracked.
"""

import ast
from dataclasses import fields as dataclass_fields

from core.pipeline.reconstructor import (
    ReconstructionResult,
    _normalize_file_content,
    reconstruct_strict,
)


# ============================================================
# 1. Every ReconstructionResult field must be logged
# ============================================================

EXPECTED_RECON_EVENT_KEYS = {
    # Parse routing (from RoutingResult, not ReconstructionResult)
    "parsing_mode",
    "strict_parse_valid",
    "recovery_parse_valid",
    "strict_structurally_valid",
    "recovery_structurally_valid",
    "structural_errors",
    "recovery_used",
    "divergence_detected",
    "execution_eligible",
    "executed",
    # From ReconstructionResult
    "recon_status",
    "reconstruction_mode",
    "files_changed",
    "files_missing",
    "files_extra",
    "files_total",
    "syntax_errors",
    "format_violation",
    "content_normalized",
    "normalization_log",
    "recovery_applied",
    "recovery_types",
    "semantic_diagnostics",
    # Added by caller
    "artifact_id",
}


def test_all_reconstruction_result_fields_are_logged():
    """Every non-content field of ReconstructionResult must appear in the event."""
    recon_fields = {f.name for f in dataclass_fields(ReconstructionResult)}
    # 'files' is intentionally excluded (large content, not logged inline)
    recon_fields.discard("files")

    # Map ReconstructionResult field names to event key names
    field_to_event_key = {
        "status": "recon_status",
        "changed_files": "files_changed",
        "missing_files": "files_missing",
        "extra_files": "files_extra",
    }

    for field_name in recon_fields:
        event_key = field_to_event_key.get(field_name, field_name)
        assert event_key in EXPECTED_RECON_EVENT_KEYS, (
            f"ReconstructionResult.{field_name} (event key: {event_key}) "
            f"is not in EXPECTED_RECON_EVENT_KEYS. "
            f"If this field was added to ReconstructionResult, "
            f"add it to _build_reconstruction_section() in execution_v2.py "
            f"and to this test."
        )


# ============================================================
# 2. Prefix stripping recovery
# ============================================================

def test_prefix_strip_fully_updated():
    code = 'FULLY UPDATED\n\nimport os\n\ndef foo():\n    pass'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is True
    assert normalized.startswith("import os")
    ast.parse(normalized)  # must be valid Python


def test_prefix_strip_full_file_contents():
    code = 'FULL FILE CONTENTS:\n\nfrom config import get_config\n\ndef test(): pass'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is True
    assert normalized.startswith("from config")
    ast.parse(normalized)


def test_prefix_strip_dashes():
    code = '---\nimport os\ndef bar(): pass'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is True
    assert normalized.startswith("import os")
    ast.parse(normalized)


def test_prefix_strip_replace_with():
    code = 'REPLACE with:\n\nclass Foo:\n    pass'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is True
    assert normalized.startswith("class Foo")
    ast.parse(normalized)


def test_no_strip_clean_python():
    code = 'import os\n\ndef foo():\n    return os.getcwd()'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is False
    assert normalized == code


def test_no_strip_docstring_start():
    code = '"""Module docstring."""\n\nimport os\n'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is False
    assert normalized == code


def test_no_strip_comment_start():
    code = '# This is a comment\nimport os\n'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is False
    assert normalized == code


def test_fence_strip_in_value():
    code = '```python\nimport os\ndef foo(): pass\n```'
    normalized, stripped = _normalize_file_content(code)
    assert "```" not in normalized
    assert normalized.strip().startswith("import os")
    ast.parse(normalized)


def test_prefix_strip_trailing_fence():
    code = 'FULLY UPDATED:\n\nimport os\ndef foo(): pass\n```'
    normalized, stripped = _normalize_file_content(code)
    assert stripped is True
    assert "```" not in normalized
    ast.parse(normalized)


# ============================================================
# 3. Recovery type tracking through reconstruct_strict
# ============================================================

def test_reconstruct_tracks_prefix_strip():
    """reconstruct_strict must record file_value_prefix_stripped in recovery_types."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "FULLY UPDATED\n\ndef fixed():\n    return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS", f"Expected SUCCESS, got {result.status}"
    assert result.recovery_applied is True
    assert "file_value_prefix_stripped" in result.recovery_types
    assert any("file_value_prefix_stripped:test.py" in entry
               for entry in result.normalization_log)


def test_reconstruct_no_recovery_on_clean_code():
    """Clean code must not trigger any recovery."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "def fixed():\n    return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert result.recovery_applied is False
    assert result.recovery_types == []
    assert result.normalization_log == []


def test_reconstruct_unchanged_sentinel():
    """UNCHANGED sentinel must be accepted without recovery."""
    manifest_paths = ["a.py", "b.py"]
    manifest_files = {"a.py": "def a(): pass", "b.py": "def b(): pass"}
    model_files = {"a.py": "UNCHANGED", "b.py": "def b_fixed(): return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "a.py" not in result.changed_files
    assert "b.py" in result.changed_files


def test_reconstruct_invalid_code_no_recovery():
    """Diff output cannot be recovered — must fail as RECON_INVALID_CODE."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "diff --git a/test.py b/test.py\n--- a/test.py\n+++ b/test.py"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "RECON_INVALID_CODE"
    assert "test.py" in result.syntax_errors


# ============================================================
# 5. Missing file auto-fill recovery
# ============================================================

def test_reconstruct_auto_fills_omitted_files():
    """Omitted files must be auto-filled with UNCHANGED, marked as recovery."""
    manifest_paths = ["a.py", "b.py", "c.py"]
    manifest_files = {
        "a.py": "def a(): pass",
        "b.py": "def b(): pass",
        "c.py": "def c(): pass",
    }
    # Model only provides a.py (the one it fixed), omits b.py and c.py
    model_files = {"a.py": "def a_fixed():\n    return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert result.recovery_applied is True
    assert "missing_files_auto_filled" in result.recovery_types
    assert any("missing_file_auto_filled:b.py" in e
               for e in result.normalization_log)
    assert any("missing_file_auto_filled:c.py" in e
               for e in result.normalization_log)
    # a.py was changed, b.py and c.py were auto-filled as unchanged
    assert "a.py" in result.changed_files
    assert "b.py" not in result.changed_files
    assert "c.py" not in result.changed_files
    # All files present in output
    assert set(result.files.keys()) == {"a.py", "b.py", "c.py"}


def test_reconstruct_auto_fill_single_missing():
    """Single omitted file in multi-file case."""
    manifest_paths = ["main.py", "helper.py"]
    manifest_files = {"main.py": "def main(): pass", "helper.py": "def help(): pass"}
    model_files = {"main.py": "def main():\n    return 42\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "missing_files_auto_filled" in result.recovery_types
    assert result.files["helper.py"] == "def help(): pass"  # original content


def test_reconstruct_no_auto_fill_when_all_present():
    """No auto-fill when model provides all files."""
    manifest_paths = ["a.py", "b.py"]
    manifest_files = {"a.py": "def a(): pass", "b.py": "def b(): pass"}
    model_files = {"a.py": "def a_fixed(): return True\n", "b.py": "UNCHANGED"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "missing_files_auto_filled" not in result.recovery_types


# ============================================================
# 4. Fence stripping tracking
# ============================================================

def test_reconstruct_tracks_fence_strip():
    """Markdown fence stripping must be recorded."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "```python\ndef fixed():\n    return True\n```"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert result.recovery_applied is True
    assert "fence_stripped" in result.recovery_types
    assert any("fence_stripped:test.py" in entry
               for entry in result.normalization_log)


# ============================================================
# 6. Leading whitespace dedent recovery
# ============================================================

def test_dedent_single_leading_space():
    """Single leading space on line 1 — AST retry strips first line."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": " import os\nprint(1)"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "leading_whitespace_stripped" in result.recovery_types


def test_dedent_full_indent():
    """Entire code indented 4 spaces — AST retry with textwrap.dedent."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "    def foo():\n        return 1"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "leading_whitespace_stripped" in result.recovery_types


def test_no_dedent_when_parse_ok():
    """Valid code must not trigger leading_whitespace_stripped recovery."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": "def fixed():\n    return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert "leading_whitespace_stripped" not in result.recovery_types


def test_reconstruct_tracks_leading_whitespace_strip():
    """AST-gated dedent retry must record leading_whitespace_stripped."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    # Single leading space — fails ast.parse, first-line strip fixes it
    model_files = {"test.py": " def fixed():\n    return True\n"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "SUCCESS"
    assert result.recovery_applied is True
    assert "leading_whitespace_stripped" in result.recovery_types
    assert any("leading_whitespace_stripped:test.py" in entry
               for entry in result.normalization_log)


def test_no_false_positive_on_syntax_error():
    """Genuinely broken code must not be masked by dedent retry."""
    manifest_paths = ["test.py"]
    manifest_files = {"test.py": "def original(): pass"}
    model_files = {"test.py": " def foo(\n    return 1"}

    result = reconstruct_strict(manifest_paths, manifest_files, model_files)

    assert result.status == "RECON_INVALID_CODE"
    assert "test.py" in result.syntax_errors
    assert "leading_whitespace_stripped" not in result.recovery_types
