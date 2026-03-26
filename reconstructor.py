"""Strict file-level reconstruction for T3 benchmark.

Maps LLM output (file-dict format) back to case files.
Primary path: FAIL on any missing file. No fallback.
Salvage path: secondary analysis only.
"""

import ast
import logging
import re
from dataclasses import dataclass, field

_log = logging.getLogger("t3.reconstructor")


def _normalize_file_content(content: str) -> str:
    """Normalize model-produced file content before AST validation.

    Handles two common model formatting artifacts:
    1. Markdown fences: model wraps code in ```python ... ```
    2. Escaped newlines: model returns \\n instead of real newlines

    Returns the normalized content string. Does NOT modify content that
    is already valid Python.
    """
    if not content or not content.strip():
        return content

    normalized = content

    # Strip markdown fences (```python ... ``` or ``` ... ```)
    # Only strip if the content starts with a fence line
    stripped = normalized.strip()
    if stripped.startswith("```"):
        # Remove opening fence line
        first_newline = stripped.find("\n")
        if first_newline != -1:
            after_open = stripped[first_newline + 1:]
        else:
            after_open = ""
        # Remove closing fence
        if after_open.rstrip().endswith("```"):
            last_fence = after_open.rstrip().rfind("```")
            after_open = after_open[:last_fence]
        normalized = after_open

    # Unescape \\n and \\t when content has NO real newlines
    # This distinguishes:
    #   "def f():\\n    pass" (escaped, 0 real newlines → unescape)
    #   "def f():\n    pass" (normal, has real newlines → leave alone)
    if "\n" not in normalized and "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n").replace("\\t", "\t")
        _log.info("CONTENT_NORMALIZED: unescaped \\\\n/\\\\t in file content (len=%d→%d)",
                  len(content), len(normalized))

    if normalized != content:
        _log.info("CONTENT_NORMALIZED: file content changed (len=%d→%d, fences=%s, unescape=%s)",
                  len(content), len(normalized),
                  content.strip().startswith("```"),
                  "\n" not in content and "\\n" in content)

    return normalized


@dataclass
class ReconstructionResult:
    status: str                          # SUCCESS, FAILED_MISSING_FILES, FAILED_EMPTY_FILES, FAILED_SYNTAX_ERRORS
    files: dict[str, str]                # rel_path -> content (populated on SUCCESS or FAILED_SYNTAX_ERRORS)
    changed_files: set[str] = field(default_factory=set)
    missing_files: set[str] = field(default_factory=set)
    extra_files: set[str] = field(default_factory=set)
    syntax_errors: dict[str, str] = field(default_factory=dict)
    format_violation: bool = False
    reconstruction_mode: str = "strict"  # "strict" or "salvaged"
    # Observability fields (Phase 1)
    content_normalized: bool = False
    normalization_log: list[str] = field(default_factory=list)
    recovery_applied: bool = False
    recovery_types: list[str] = field(default_factory=list)


def reconstruct_strict(manifest_file_paths: list[str],
                       manifest_files: dict[str, str],
                       model_files: dict[str, str]) -> ReconstructionResult:
    """Primary reconstruction. FAILS if any expected file is missing.

    Args:
        manifest_file_paths: ordered list of expected file relative paths
        manifest_files: rel_path -> original content (for UNCHANGED resolution)
        model_files: rel_path -> model content or "UNCHANGED"

    Returns:
        ReconstructionResult with status indicating success or failure type.
    """
    expected = set(manifest_file_paths)
    provided = set(model_files.keys())
    missing = expected - provided
    extra = provided - expected

    if missing:
        _log.warning(
            "RECONSTRUCTION FAILED: %d missing files: %s",
            len(missing), sorted(missing),
        )
        return ReconstructionResult(
            status="FAILED_MISSING_FILES",
            files={},
            missing_files=missing,
            extra_files=extra,
            format_violation=True,
        )

    final_files = {}
    changed = set()
    syntax_errors = {}
    normalization_log = []
    recovery_types_set = set()

    for rel_path in manifest_file_paths:
        value = model_files[rel_path]

        if value.strip() == "UNCHANGED":
            if rel_path not in manifest_files:
                _log.warning(
                    "UNCHANGED for unknown file %s -- treating as missing", rel_path
                )
                return ReconstructionResult(
                    status="FAILED_MISSING_FILES",
                    files={},
                    missing_files={rel_path},
                    extra_files=extra,
                    format_violation=True,
                )
            final_files[rel_path] = manifest_files[rel_path]
            continue

        if not isinstance(value, str) or not value.strip():
            _log.warning("RECONSTRUCTION FAILED: empty/invalid value for %s", rel_path)
            return ReconstructionResult(
                status="FAILED_EMPTY_FILES",
                files={},
                format_violation=True,
            )

        # Normalize content: strip markdown fences, unescape \\n
        normalized = _normalize_file_content(value)

        # Track normalization
        if normalized != value:
            if value.strip().startswith("```"):
                normalization_log.append(f"fence_stripped:{rel_path}")
                recovery_types_set.add("fence_stripped")
            if "\n" not in value and "\\n" in value:
                normalization_log.append(f"newlines_unescaped:{rel_path}")
                recovery_types_set.add("newlines_unescaped")

        # AST validation on NORMALIZED content
        try:
            ast.parse(normalized)
        except SyntaxError as e:
            syntax_errors[rel_path] = str(e)

        final_files[rel_path] = normalized
        changed.add(rel_path)

    was_normalized = len(normalization_log) > 0
    recovery_types = sorted(recovery_types_set)

    if syntax_errors:
        _log.warning(
            "RECONSTRUCTION FAILED: syntax errors in %d files: %s",
            len(syntax_errors), list(syntax_errors.keys()),
        )
        return ReconstructionResult(
            status="FAILED_SYNTAX_ERRORS",
            files=final_files,
            changed_files=changed,
            extra_files=extra,
            syntax_errors=syntax_errors,
            format_violation=False,
            content_normalized=was_normalized,
            normalization_log=normalization_log,
            recovery_applied=was_normalized,
            recovery_types=recovery_types,
        )

    return ReconstructionResult(
        status="SUCCESS",
        files=final_files,
        changed_files=changed,
        extra_files=extra,
        content_normalized=was_normalized,
        normalization_log=normalization_log,
        recovery_applied=was_normalized,
        recovery_types=recovery_types,
    )


def reconstruct_salvage(manifest_file_paths: list[str],
                        manifest_files: dict[str, str],
                        model_files: dict[str, str]) -> ReconstructionResult:
    """Salvage reconstruction for secondary analysis. Fills missing with originals.

    MUST NOT flow into primary metrics. Result tagged reconstruction_mode="salvaged".
    """
    expected = set(manifest_file_paths)
    provided = set(model_files.keys())
    missing = expected - provided
    extra = provided - expected

    final_files = {}
    changed = set()
    syntax_errors = {}

    for rel_path in manifest_file_paths:
        if rel_path not in model_files:
            # Salvage: use original
            final_files[rel_path] = manifest_files[rel_path]
            continue

        value = model_files[rel_path]

        if value.strip() == "UNCHANGED":
            final_files[rel_path] = manifest_files[rel_path]
            continue

        if not isinstance(value, str) or not value.strip():
            final_files[rel_path] = manifest_files[rel_path]
            continue

        try:
            ast.parse(value)
        except SyntaxError as e:
            syntax_errors[rel_path] = str(e)

        final_files[rel_path] = value
        changed.add(rel_path)

    status = "SALVAGED"
    if syntax_errors:
        status = "SALVAGED_WITH_SYNTAX_ERRORS"

    return ReconstructionResult(
        status=status,
        files=final_files,
        changed_files=changed,
        missing_files=missing,
        extra_files=extra,
        syntax_errors=syntax_errors,
        format_violation=len(missing) > 0,
        reconstruction_mode="salvaged",
    )
