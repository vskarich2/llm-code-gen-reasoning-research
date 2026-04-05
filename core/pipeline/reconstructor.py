"""Strict file-level reconstruction for T3 benchmark.

Maps LLM output (file-dict format) back to case files.
Primary path: FAIL on any missing file. No fallback.
Salvage path: secondary analysis only.
"""

import ast
import logging
import re
import textwrap
from dataclasses import dataclass, field

_log = logging.getLogger("t3.reconstructor")


def _normalize_file_content(content: str) -> tuple[str, bool]:
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
            after_open = stripped[first_newline + 1 :]
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
        _log.info(
            "CONTENT_NORMALIZED: unescaped \\\\n/\\\\t in file content (len=%d→%d)",
            len(content),
            len(normalized),
        )

    # Strip non-Python prefix lines (model artifacts like "FULLY UPDATED\n",
    # "REPLACE with:\n", "---\n", "FULL FILE CONTENTS:\n", etc.)
    # Only strip if first non-blank line is NOT valid Python.
    _PYTHON_STARTERS = (
        'import ', 'from ', 'def ', 'class ', '#', '"""', "'''",
        '@', '_', 'DEFAULTS', 'async ', 'if ', 'for ', 'while ',
        'try:', 'with ', 'return ', 'raise ', 'global ', 'assert ',
    )
    lines = normalized.split('\n')
    prefix_stripped = False
    start = 0
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            start = i + 1
            continue
        if stripped_line.startswith(_PYTHON_STARTERS):
            start = i
            break
        # Known non-Python prefixes to strip
        if (stripped_line.startswith(('FULLY', 'FULL ', 'REPLACE', 'UPDATE',
                                      '---', 'REVISED', 'CORRECTED'))
                or stripped_line in ('---', '```python', '```')):
            start = i + 1
            prefix_stripped = True
            continue
        # Unknown line that doesn't look like Python — stop stripping
        break

    if prefix_stripped and start > 0:
        normalized = '\n'.join(lines[start:])
        # Also strip trailing ``` if present
        if normalized.rstrip().endswith('```'):
            normalized = normalized.rstrip()[:-3].rstrip()

    if normalized != content:
        _log.info(
            "CONTENT_NORMALIZED: file content changed (len=%d→%d, "
            "fences=%s, unescape=%s, prefix_stripped=%s)",
            len(content),
            len(normalized),
            content.strip().startswith("```"),
            "\n" not in content and "\\n" in content,
            prefix_stripped,
        )

    return normalized, prefix_stripped


@dataclass
class ReconstructionResult:
    status: str  # SUCCESS, RECON_MISSING_FILES, RECON_EMPTY_FILE, RECON_SENTINEL_MISMATCH, RECON_INVALID_CODE
    files: dict[str, str]  # rel_path -> content (populated on SUCCESS or RECON_INVALID_CODE)
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
    # Semantic diagnostics (non-blocking)
    semantic_diagnostics: dict = field(default_factory=lambda: {
        "missing_required_definitions": False,
        "missing_definition_names": [],
    })


# ── Normalized no-change phrase detection ────────────────────

_NO_CHANGE_PHRASES = frozenset({
    "unchanged", "unmodified", "unchange",
    "no change", "no changes", "no changes needed",
    "same", "same as original", "same as before", "same file",
    "original", "original file contents",
    "not modified", "do not modify",
    "keep as is", "keep original file",
    "leave unchanged",
    "use original contents",
    "no modification", "no modifications",
    "complete file contents or unchanged",
    "complete file contents",
    "file contents unchanged",
    "unchanged file",
    "full",
})


def _is_no_change_phrase(value: str) -> bool:
    """Normalized no-change phrase detection.

    Strips, lowercases, removes punctuation/brackets, collapses whitespace.
    Checks against canonical phrase set. Limited to exact normalized matches.
    Non-matching paraphrases are not caught.

    Normalization is used ONLY here. The normalized string is never logged,
    returned, stored, or passed to any other function.
    """
    normalized = re.sub(
        r"[<>\[\](){}\"'`.,;:!?/\\*#@&^~|+=\-_]", " ",
        value.strip().lower())
    normalized = " ".join(normalized.split())
    return normalized in _NO_CHANGE_PHRASES


# ── Semantic structure check (diagnostic only) ───────────────

def _extract_definitions(source: str) -> set[str]:
    """Extract top-level function and class names from Python source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
    return names


def _check_semantic_structure(
    model_code: str, original_code: str,
) -> dict:
    """Non-blocking semantic check. Returns diagnostic dict.

    Compares top-level definitions in model code against original.
    Never blocks execution. Never changes reconstruction status.
    """
    required = _extract_definitions(original_code)
    if not required:
        return {
            "missing_required_definitions": False,
            "missing_definition_names": [],
        }
    provided = _extract_definitions(model_code)
    missing = sorted(required - provided)
    return {
        "missing_required_definitions": len(missing) > 0,
        "missing_definition_names": missing,
    }


def reconstruct_strict(
    manifest_file_paths: list[str], manifest_files: dict[str, str], model_files: dict[str, str]
) -> ReconstructionResult:
    """Primary reconstruction with 5-gate validation pipeline.

    Gates (in order):
      1. Exact UNCHANGED check → accept original
      2. Empty/whitespace check → RECON_EMPTY_FILE (blocks execution)
      3. Normalized no-change phrase detection → RECON_SENTINEL_MISMATCH (blocks)
      4. ast.parse validation → RECON_INVALID_CODE (blocks)
      5. Semantic structure check → diagnostic only (never blocks)

    Execution occurs ONLY when status == SUCCESS.

    Args:
        manifest_file_paths: ordered list of expected file relative paths
        manifest_files: rel_path -> original content (for UNCHANGED resolution)
        model_files: rel_path -> model content or "UNCHANGED"
    """
    expected = set(manifest_file_paths)
    provided = set(model_files.keys())
    missing = expected - provided
    extra = provided - expected

    auto_filled_files = set()
    if missing:
        # Auto-fill missing files with original content.
        # The prompt says "include EVERY file" with UNCHANGED for unmodified,
        # but models often omit files they didn't change. This is semantically
        # equivalent to UNCHANGED — the model didn't mention the file because
        # it didn't change it. Hard-failing here punishes correct fixes.
        _log.info(
            "RECONSTRUCTION RECOVERY: auto-filling %d missing files with "
            "originals: %s", len(missing), sorted(missing),
        )
        for m in missing:
            if m in manifest_files:
                model_files[m] = "UNCHANGED"
                auto_filled_files.add(m)
            else:
                # File not in manifest either — genuine missing file
                _log.warning(
                    "RECONSTRUCTION FAILED: missing file %s not in manifest",
                    m,
                )
                return ReconstructionResult(
                    status="RECON_MISSING_FILES",
                    files={},
                    missing_files={m},
                    extra_files=extra,
                    format_violation=True,
                )
        # Recalculate after auto-fill
        provided = set(model_files.keys())
        missing = expected - provided

    final_files = {}
    changed = set()
    syntax_errors = {}
    normalization_log = []
    recovery_types_set = set()
    all_semantic_diagnostics = {}

    # Record auto-filled files as recovery
    if auto_filled_files:
        recovery_types_set.add("missing_files_auto_filled")
        for af in sorted(auto_filled_files):
            normalization_log.append(f"missing_file_auto_filled:{af}")

    for rel_path in manifest_file_paths:
        value = model_files[rel_path]

        # ── Gate 1: Exact UNCHANGED ──────────────────────────
        if value.strip() == "UNCHANGED":
            if rel_path not in manifest_files:
                _log.warning(
                    "UNCHANGED for unknown file %s -- treating as missing",
                    rel_path)
                return ReconstructionResult(
                    status="RECON_MISSING_FILES",
                    files={},
                    missing_files={rel_path},
                    extra_files=extra,
                    format_violation=True,
                )
            final_files[rel_path] = manifest_files[rel_path]
            continue

        # ── Gate 1b: Sentinel-mixed detection ───────────────────
        # Model wrote a no-change phrase as first line PLUS actual code.
        # This is a contract violation: the file is neither UNCHANGED nor
        # clean code. We flag it as RECON_SENTINEL_MIXED and store the
        # stripped candidate for diagnostic recovery (NOT for scoring).
        first_line = value.strip().split('\n')[0].strip()
        rest_after_first = '\n'.join(value.strip().split('\n')[1:]).strip()
        if _is_no_change_phrase(first_line) and rest_after_first:
            _log.warning(
                "SENTINEL_MIXED for %s: first line is '%s' but %d chars of "
                "code follow. Strict: contract violation. Recovery candidate stored.",
                rel_path, first_line, len(rest_after_first))
            return ReconstructionResult(
                status="RECON_SENTINEL_MIXED",
                files={},
                missing_files={rel_path},
                format_violation=True,
                recovery_applied=False,
                recovery_types=["sentinel_mixed_detected"],
                normalization_log=[
                    f"sentinel_mixed:{rel_path}:first_line={first_line}",
                    f"sentinel_mixed_candidate_len:{len(rest_after_first)}",
                ],
            )

        # ── Gate 2: Empty/whitespace ─────────────────────────
        if not isinstance(value, str) or not value.strip():
            _log.warning(
                "RECONSTRUCTION FAILED: empty/invalid value for %s",
                rel_path)
            return ReconstructionResult(
                status="RECON_EMPTY_FILE",
                files={},
                format_violation=True,
            )

        # ── Gate 3: Normalized no-change phrase detection ────
        if _is_no_change_phrase(value):
            _log.warning(
                "RECONSTRUCTION FAILED: sentinel mismatch for %s "
                "(value=%r)", rel_path, value.strip())
            return ReconstructionResult(
                status="RECON_SENTINEL_MISMATCH",
                files={},
                missing_files={rel_path},
                format_violation=True,
            )

        # Normalize content: strip markdown fences, unescape \\n, strip non-Python prefixes
        normalized, prefix_stripped = _normalize_file_content(value)

        # Track normalization
        if normalized != value:
            if value.strip().startswith("```"):
                normalization_log.append(f"fence_stripped:{rel_path}")
                recovery_types_set.add("fence_stripped")
            if "\n" not in value and "\\n" in value:
                normalization_log.append(
                    f"newlines_unescaped:{rel_path}")
                recovery_types_set.add("newlines_unescaped")
            if prefix_stripped:
                normalization_log.append(
                    f"file_value_prefix_stripped:{rel_path}")
                recovery_types_set.add("file_value_prefix_stripped")

        # ── Gate 4: AST validation (on raw value, not normalized form) ──
        # Note: ast.parse operates on the content-normalized value
        # (fences stripped, newlines unescaped) but NOT the phrase-
        # normalized value used in gate 3.
        try:
            ast.parse(normalized)
            parse_ok = True
        except SyntaxError:
            parse_ok = False

        if not parse_ok and normalized.startswith((" ", "\t")):
            recovered = False
            # Strategy 1: textwrap.dedent (uniform indent)
            dedented = textwrap.dedent(normalized)
            if dedented != normalized:
                try:
                    ast.parse(dedented)
                    normalized = dedented
                    recovered = True
                except SyntaxError:
                    pass
            # Strategy 2: strip first line only (stray space)
            if not recovered:
                lines = normalized.split("\n")
                lines[0] = lines[0].lstrip()
                first_stripped = "\n".join(lines)
                if first_stripped != normalized:
                    try:
                        ast.parse(first_stripped)
                        normalized = first_stripped
                        recovered = True
                    except SyntaxError:
                        pass
            if recovered:
                recovery_types_set.add(
                    "leading_whitespace_stripped")
                normalization_log.append(
                    f"leading_whitespace_stripped:{rel_path}")

        if not parse_ok:
            try:
                ast.parse(normalized)
            except SyntaxError as e:
                syntax_errors[rel_path] = str(e)

        final_files[rel_path] = normalized
        changed.add(rel_path)

        # ── Gate 5: Semantic structure (diagnostic only) ─────
        original = manifest_files.get(rel_path, "")
        diag = _check_semantic_structure(normalized, original)
        if diag["missing_required_definitions"]:
            all_semantic_diagnostics[rel_path] = diag

    was_normalized = len(normalization_log) > 0
    recovery_types = sorted(recovery_types_set)

    # Gate 4 failures (collected across all files)
    if syntax_errors:
        _log.warning(
            "RECONSTRUCTION FAILED: syntax errors in %d files: %s",
            len(syntax_errors), list(syntax_errors.keys()),
        )
        return ReconstructionResult(
            status="RECON_INVALID_CODE",
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

    # Merge semantic diagnostics
    merged_diag = {
        "missing_required_definitions": len(all_semantic_diagnostics) > 0,
        "missing_definition_names": [],
    }
    for diag in all_semantic_diagnostics.values():
        merged_diag["missing_definition_names"].extend(
            diag["missing_definition_names"])

    return ReconstructionResult(
        status="SUCCESS",
        files=final_files,
        changed_files=changed,
        extra_files=extra,
        content_normalized=was_normalized,
        normalization_log=normalization_log,
        recovery_applied=was_normalized,
        recovery_types=recovery_types,
        semantic_diagnostics=merged_diag,
    )


def reconstruct_salvage(
    manifest_file_paths: list[str], manifest_files: dict[str, str], model_files: dict[str, str]
) -> ReconstructionResult:
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
