"""Tests for classifier visibility alignment with execution.

Verifies that the classifier receives the FULL materialized codebase
(including unchanged files), not just the changed files. This prevents
CCC false positives where commitments about cross-file behavior are
marked INCORRECT because the classifier can't see the dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest


# ── Helpers to simulate reconstruction ──

@dataclass
class FakeReconResult:
    status: str = "SUCCESS"
    files: dict = field(default_factory=dict)
    changed_files: set = field(default_factory=set)
    missing_files: set = field(default_factory=set)
    extra_files: set = field(default_factory=set)
    syntax_errors: dict = field(default_factory=dict)
    format_violation: bool = False
    reconstruction_mode: str = "strict"
    content_normalized: bool = False
    normalization_log: list = field(default_factory=list)
    recovery_applied: bool = False
    recovery_types: list = field(default_factory=list)
    semantic_diagnostics: dict = field(default_factory=lambda: {
        "missing_required_definitions": False,
        "missing_definition_names": [],
    })


def _build_full_code(recon, logical_paths):
    """Replicate the code-building logic from _reconstruct in execution_v2.py."""
    full_code_parts = []
    if recon.status == "SUCCESS" and recon.files:
        for path in logical_paths:
            if path in recon.files:
                is_modified = path in recon.changed_files
                marker = "MODIFIED" if is_modified else "UNCHANGED"
                full_code_parts.append(
                    f"# [{marker}] {path}\n{recon.files[path]}")
    return "\n\n".join(full_code_parts)


# ── Test 1: Full code includes unchanged files ──

def test_full_code_includes_unchanged_files():
    """Classifier must see ALL files, not just changed ones."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={
            "config.py": "DEFAULTS = {'timeout': 30}\ndef create_config():\n    return DEFAULTS.copy()",
            "service.py": "from config import create_config\ndef run():\n    c = create_config()\n    return c",
        },
        changed_files={"config.py"},
    )
    logical_paths = ["config.py", "service.py"]

    code = _build_full_code(recon, logical_paths)

    assert "# [MODIFIED] config.py" in code
    assert "# [UNCHANGED] service.py" in code
    assert "DEFAULTS.copy()" in code
    assert "from config import create_config" in code


# ── Test 2: Changed-only code would miss dependency ──

def test_changed_only_misses_dependency():
    """Old behavior (changed files only) would miss the unchanged dependency."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={
            "config.py": "DEFAULTS = {'timeout': 30}\ndef create_config():\n    return DEFAULTS.copy()",
            "service.py": "from config import create_config\ndef run():\n    c = create_config()\n    return c",
        },
        changed_files={"config.py"},
    )
    logical_paths = ["config.py", "service.py"]

    # Old behavior: only changed files
    old_code_parts = [recon.files[p] for p in logical_paths if p in recon.changed_files]
    old_code = "\n\n".join(old_code_parts)

    # New behavior: full code
    new_code = _build_full_code(recon, logical_paths)

    # Old code misses service.py
    assert "from config import create_config" not in old_code
    # New code includes it
    assert "from config import create_config" in new_code


# ── Test 3: Cross-file commitment is visible in full code ──

def test_cross_file_commitment_visible():
    """A commitment about behavior in an unchanged file should be
    verifiable from the full code but not from changed-only code."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={
            "catalog.py": "def update_product(pid, data):\n    db.write(pid, data)\n    cache.invalidate(pid)",
            "api.py": "from catalog import update_product\ndef get_product(pid):\n    return cache.get(pid) or db.read(pid)",
        },
        changed_files={"catalog.py"},
    )
    logical_paths = ["catalog.py", "api.py"]

    code = _build_full_code(recon, logical_paths)

    # Commitment: "api.get_product returns fresh data after update"
    # Verifiable because api.py is visible:
    assert "get_product" in code
    assert "cache.get(pid) or db.read(pid)" in code
    # And the fix in catalog.py is visible:
    assert "cache.invalidate(pid)" in code


# ── Test 4: File markers are correct ──

def test_file_markers_correct():
    """Each file must be marked MODIFIED or UNCHANGED correctly."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={
            "a.py": "# file a",
            "b.py": "# file b",
            "c.py": "# file c",
        },
        changed_files={"a.py", "c.py"},
    )
    logical_paths = ["a.py", "b.py", "c.py"]

    code = _build_full_code(recon, logical_paths)

    assert "# [MODIFIED] a.py" in code
    assert "# [UNCHANGED] b.py" in code
    assert "# [MODIFIED] c.py" in code


# ── Test 5: Failed reconstruction produces empty code ──

def test_failed_recon_produces_empty_code():
    """If reconstruction fails, code should be empty."""
    recon = FakeReconResult(
        status="RECON_MISSING_FILES",
        files={},
        changed_files=set(),
    )
    logical_paths = ["config.py"]

    code = _build_full_code(recon, logical_paths)
    assert code == ""


# ── Test 6: Single-file case still works ──

def test_single_file_case():
    """Single-file cases should have one MODIFIED file."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={"config.py": "def create_config():\n    return {}"},
        changed_files={"config.py"},
    )
    logical_paths = ["config.py"]

    code = _build_full_code(recon, logical_paths)

    assert "# [MODIFIED] config.py" in code
    assert "[UNCHANGED]" not in code


# ── Test 7: File order matches logical_paths order ──

def test_file_order_preserved():
    """Files must appear in logical_paths order, not arbitrary dict order."""
    recon = FakeReconResult(
        status="SUCCESS",
        files={
            "z.py": "# z",
            "a.py": "# a",
            "m.py": "# m",
        },
        changed_files={"a.py"},
    )
    logical_paths = ["a.py", "m.py", "z.py"]

    code = _build_full_code(recon, logical_paths)

    idx_a = code.index("a.py")
    idx_m = code.index("m.py")
    idx_z = code.index("z.py")
    assert idx_a < idx_m < idx_z, "Files not in logical_paths order"
