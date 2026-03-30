"""V2 generation output parser — three-tier architecture.

Three parsers, three questions, one data model:
  EXECUTION: "Can we extract a usable JSON dict?" (drives pipeline)
  FORMAT:    "Did the model follow output instructions exactly?" (diagnostic)
  RECOVERY:  "Could formatting repairs recover the output?" (diagnostic)

See docs/parser_v2_three_tier_design.md for full specification.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from contracts_v2 import (
    validate_generation_fields, CONDITION_TO_SCHEMA, SCHEMA_REQUIRED_FIELDS,
)

_log = logging.getLogger("t3.parser_v2")


# ============================================================
# DATA MODEL
# ============================================================


@dataclass
class ParsedGenerationV2:
    """Canonical parsed v2 generation output."""

    # Core fields (unchanged interface)
    parse_status: str               # "success" | "partial" | "invalid" | "failed"
    schema_variant: str             # "baseline_v2" | "leg_v2" | "lean_v2"
    full_json: dict | None
    files_dict: dict | None
    parse_error: str | None
    raw_response_text: str
    parser_variant: str = "parser_v2_generation"
    validation_status: str = ""
    validation_errors: list[str] = field(default_factory=list)

    # Decomposed validity
    parse_valid: bool = False
    schema_valid: bool = False

    # Parser identity
    parser_tier: str = "execution"  # "execution" | "format" | "recovery"

    # Format diagnostic (format parser only)
    format_valid: bool = False
    format_error: str | None = None

    # Recovery diagnostic (recovery parser only)
    recovery_type: str | None = None
    recovery_steps: list[str] = field(default_factory=list)
    execution_equivalent: bool = True

    # Hardening signals
    possible_mis_extraction: bool = False
    schema_normalization_applied: bool = False


# ============================================================
# SHARED UTILITIES (pure, no side effects)
# ============================================================


def _strip_fences(text: str) -> str:
    """Strip markdown code fences if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        stripped = stripped[first_nl + 1:] if first_nl != -1 else ""
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _find_json_block(text: str) -> tuple[str | None, int]:
    """Find first balanced top-level JSON object via stack-based brace parsing.

    Returns (json_str, end_pos). end_pos is the index after the closing '}'.
    Returns (None, -1) if no balanced block found.
    """
    start = text.find("{")
    if start == -1:
        return None, -1

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if c == "\\":
                escape_next = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None, -1


def _count_json_objects(text: str) -> int:
    """Count top-level JSON objects in text."""
    count = 0
    pos = 0
    while pos < len(text):
        block, end_pos = _find_json_block(text[pos:])
        if block is None:
            break
        count += 1
        pos += end_pos
    return count


def _fix_invalid_escapes(text: str) -> tuple[str, bool]:
    """Fix invalid JSON escape sequences (e.g. \\s, \\1, \\p from regex/Python).

    Returns (fixed_text, was_fixed).
    """
    # JSON only allows: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    valid_escapes = set('"\\bfnrt/')
    result = []
    fixed = False
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            next_c = text[i + 1]
            if next_c == 'u' and i + 5 < len(text):
                # \uXXXX — pass through
                result.append(text[i:i + 6])
                i += 6
                continue
            if next_c in valid_escapes:
                result.append(text[i:i + 2])
                i += 2
                continue
            # Invalid escape — double the backslash
            result.append('\\\\')
            result.append(next_c)
            i += 2
            fixed = True
        else:
            result.append(text[i])
            i += 1
    return ''.join(result), fixed


def _repair_triple_quotes(text: str) -> tuple[str, bool]:
    """Repair unescaped Python triple-quote docstrings in JSON string values.

    Returns (repaired_text, was_repaired).
    """
    try:
        json.loads(text)
        return text, False
    except (json.JSONDecodeError, TypeError):
        pass

    files_match = re.search(r'"files"\s*:\s*\{', text)
    if not files_match:
        return text, False

    prefix = text[:files_match.end()]
    rest = text[files_match.end():]

    key_pattern = re.compile(r'"([^"]+\.py)"\s*:\s*')
    keys = list(key_pattern.finditer(rest))
    if not keys:
        return text, False

    rebuilt_entries = []
    repaired = False

    for idx, key_m in enumerate(keys):
        filepath = key_m.group(1)
        val_start = key_m.end()
        val_region_end = keys[idx + 1].start() if idx + 1 < len(keys) else len(rest)

        val_region = rest[val_start:val_region_end].strip()
        if val_region.endswith(','):
            val_region = val_region[:-1].strip()
        while val_region.endswith('}'):
            val_region = val_region[:-1].strip()

        try:
            val = json.loads(val_region)
            rebuilt_entries.append(f'"{filepath}": {json.dumps(val)}')
            continue
        except (json.JSONDecodeError, TypeError):
            pass

        if val_region.startswith('"') and val_region.endswith('"') and len(val_region) > 2:
            raw_content = val_region[1:-1]
        elif val_region.startswith('"'):
            raw_content = val_region[1:]
        elif val_region.startswith('\\'):
            raw_content = val_region
        else:
            return text, False

        fixed = re.sub(r'(?<!\\)"', r'\\"', raw_content)
        rebuilt_entries.append(f'"{filepath}": "{fixed}"')
        repaired = True

    if not repaired:
        return text, False

    files_body = ',\n    '.join(rebuilt_entries)
    candidate = prefix + '\n    ' + files_body + '\n  }\n}'

    try:
        json.loads(candidate)
        _log.info("parser_v2: triple-quote repair succeeded")
        return candidate, True
    except (json.JSONDecodeError, TypeError):
        _log.debug("parser_v2: triple-quote repair assembled but still invalid")

    return text, False


# ============================================================
# SHARED VALIDATION + ASSEMBLY
# ============================================================


def _fail(schema_variant, raw, error, *, tier, **kwargs):
    """Build a FAILED ParsedGenerationV2."""
    return ParsedGenerationV2(
        parse_status="failed", schema_variant=schema_variant,
        full_json=None, files_dict=None, parse_error=error,
        raw_response_text=raw, parser_tier=tier, **kwargs,
    )


def _validate_and_build(parsed, schema_variant, raw, *, tier, **extra):
    """Validate a parsed dict and assemble ParsedGenerationV2."""
    files_dict = None
    if "files" in parsed and isinstance(parsed["files"], dict):
        files_dict = parsed["files"]

    val_status, val_errors = validate_generation_fields(parsed, schema_variant)
    schema_valid = val_status == "valid"
    parse_status = "success" if schema_valid else val_status

    if val_errors:
        _log.info("parser_v2 validation %s: %s — %s", schema_variant, val_status, val_errors)

    # Mis-extraction detection
    required = SCHEMA_REQUIRED_FIELDS.get(schema_variant, frozenset())
    missing_keys = required - set(parsed.keys())
    possible_mis = not schema_valid and len(missing_keys) >= 2

    return ParsedGenerationV2(
        parse_status=parse_status, schema_variant=schema_variant,
        full_json=parsed, files_dict=files_dict,
        parse_error=None if schema_valid else "; ".join(val_errors),
        raw_response_text=raw, parser_tier=tier,
        validation_status=val_status, validation_errors=val_errors,
        parse_valid=True, schema_valid=schema_valid,
        possible_mis_extraction=possible_mis, **extra,
    )


# ============================================================
# TIER 1: EXECUTION PARSER (pipeline primary)
# ============================================================


def parse_v2_execution(raw: str, condition: str) -> ParsedGenerationV2:
    """Extract a usable JSON dict. Tolerates fences and surrounding text.

    Rejects: empty, no JSON, multiple JSON objects, invalid JSON, non-dict.
    Does NOT repair broken JSON.
    """
    schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)
    tier = "execution"

    if not raw or not raw.strip():
        return _fail(schema_variant, raw or "", "empty_response", tier=tier)

    cleaned = _strip_fences(raw)
    json_str, end_pos = _find_json_block(cleaned)
    source = "cleaned"
    if json_str is None:
        json_str, end_pos = _find_json_block(raw)
        source = "raw"

    if json_str is None:
        return _fail(schema_variant, raw, "no_json_block", tier=tier)

    # Multiple-JSON guard
    text_used = cleaned if source == "cleaned" else raw
    if _count_json_objects(text_used) > 1:
        return _fail(schema_variant, raw, "multiple_json_objects", tier=tier)

    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        return _fail(schema_variant, raw, f"json_decode_error: {e}", tier=tier)

    if not isinstance(parsed, dict):
        return _fail(schema_variant, raw, "not_dict", tier=tier)

    return _validate_and_build(
        parsed, schema_variant, raw, tier=tier,
        parser_variant="parser_v2_execution",
    )


# ============================================================
# TIER 2: FORMAT PARSER (instruction-following diagnostic)
# ============================================================


def parse_v2_format(raw: str, condition: str) -> ParsedGenerationV2:
    """Check if model followed output instruction exactly.

    Rejects fences, extra text, multiple objects.
    Fences are a format violation (Option A).
    """
    schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)
    tier = "format"

    def fmt_fail(error):
        return _fail(
            schema_variant, raw or "", error, tier=tier,
            format_error=error,
        )

    if not raw or not raw.strip():
        return fmt_fail("empty_response")

    trimmed = raw.strip()

    # Fences = format violation
    if trimmed.startswith("```"):
        return fmt_fail("fenced_output")

    json_str, _ = _find_json_block(trimmed)
    if json_str is None:
        return fmt_fail("no_json_block")

    # Extra text check: trimmed must be ONLY the JSON block
    before = trimmed[:trimmed.index(json_str[0])].strip() if json_str[0] in trimmed else ""
    after_start = trimmed.index(json_str[0]) + len(json_str)
    after = trimmed[after_start:].strip()
    if before or after:
        return fmt_fail("extra_text")

    if _count_json_objects(trimmed) > 1:
        return fmt_fail("multiple_json_objects")

    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return fmt_fail("json_decode_error")

    if not isinstance(parsed, dict):
        return fmt_fail("not_dict")

    result = _validate_and_build(
        parsed, schema_variant, raw, tier=tier,
        parser_variant="parser_v2_format",
    )
    result.format_valid = True
    result.format_error = None
    return result


# ============================================================
# TIER 3: RECOVERY PARSER (upper bound diagnostic)
# ============================================================


def parse_v2_recovery(raw: str, condition: str) -> ParsedGenerationV2:
    """Attempt controlled, deterministic repairs to extract JSON.

    Phases: A (exec-equivalent) -> C (raw extraction) -> D/E (triple-quote)
            -> F (invalid escapes) -> G (code->files rename) -> H (fail)
    """
    schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)
    tier = "recovery"
    steps = []

    if not raw or not raw.strip():
        return _fail(
            schema_variant, raw or "", "empty_response", tier=tier,
            recovery_steps=["empty_check:FAIL"],
        )

    cleaned = _strip_fences(raw)

    # Phase A: execution-equivalent
    json_str, _ = _find_json_block(cleaned)
    if json_str is not None and _count_json_objects(cleaned) <= 1:
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                steps.append("phase_a:SUCCESS")
                result = _validate_and_build(
                    parsed, schema_variant, raw, tier=tier,
                    parser_variant="parser_v2_recovery_passthrough",
                    recovery_steps=steps, execution_equivalent=True,
                )
                return _maybe_normalize_schema(result, steps)
        except (json.JSONDecodeError, TypeError):
            pass
    steps.append("phase_a:FAIL")

    # Phase C: raw block extraction
    json_str, _ = _find_json_block(raw)
    if json_str is not None and _count_json_objects(raw) <= 1:
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                steps.append("phase_c:SUCCESS(raw_block_extraction)")
                result = _validate_and_build(
                    parsed, schema_variant, raw, tier=tier,
                    parser_variant="parser_v2_recovery",
                    recovery_type="raw_block_extraction",
                    recovery_steps=steps, execution_equivalent=False,
                )
                return _maybe_normalize_schema(result, steps)
        except (json.JSONDecodeError, TypeError):
            pass
    steps.append("phase_c:FAIL")

    # Phase D: triple-quote repair on cleaned
    repaired, did_repair = _repair_triple_quotes(cleaned)
    if did_repair:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                steps.append("phase_d:SUCCESS(triple_quote_fix)")
                result = _validate_and_build(
                    parsed, schema_variant, raw, tier=tier,
                    parser_variant="parser_v2_recovery",
                    recovery_type="triple_quote_fix",
                    recovery_steps=steps, execution_equivalent=False,
                )
                return _maybe_normalize_schema(result, steps)
        except (json.JSONDecodeError, TypeError):
            pass
    steps.append("phase_d:FAIL")

    # Phase E: triple-quote repair on raw
    repaired, did_repair = _repair_triple_quotes(raw)
    if did_repair:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                steps.append("phase_e:SUCCESS(triple_quote_fix_raw)")
                result = _validate_and_build(
                    parsed, schema_variant, raw, tier=tier,
                    parser_variant="parser_v2_recovery",
                    recovery_type="triple_quote_fix_raw",
                    recovery_steps=steps, execution_equivalent=False,
                )
                return _maybe_normalize_schema(result, steps)
        except (json.JSONDecodeError, TypeError):
            pass
    steps.append("phase_e:FAIL")

    # Phase F: invalid escape repair
    fixed_text, did_fix = _fix_invalid_escapes(cleaned)
    if did_fix:
        json_str2, _ = _find_json_block(fixed_text)
        if json_str2 is not None:
            try:
                parsed = json.loads(json_str2)
                if isinstance(parsed, dict):
                    steps.append("phase_f:SUCCESS(invalid_escape_fix)")
                    result = _validate_and_build(
                        parsed, schema_variant, raw, tier=tier,
                        parser_variant="parser_v2_recovery",
                        recovery_type="invalid_escape_fix",
                        recovery_steps=steps, execution_equivalent=False,
                    )
                    return _maybe_normalize_schema(result, steps)
            except (json.JSONDecodeError, TypeError):
                pass
    steps.append("phase_f:FAIL")

    # Phase H: all recovery failed
    steps.append("phase_h:FAIL(recovery_failed)")
    return _fail(
        schema_variant, raw, "recovery_failed", tier=tier,
        recovery_steps=steps, execution_equivalent=False,
    )


def _maybe_normalize_schema(result, steps):
    """Phase G: apply code->files rename if applicable."""
    if result.schema_valid:
        return result
    if result.full_json is None:
        return result
    fj = result.full_json
    if "files" not in fj and "code" in fj and isinstance(fj["code"], dict):
        modified = dict(fj)
        modified["files"] = modified.pop("code")
        # Re-validate with the renamed key
        val_status, val_errors = validate_generation_fields(modified, result.schema_variant)
        result.full_json = modified
        result.files_dict = modified.get("files")
        result.schema_valid = val_status == "valid"
        result.validation_status = val_status
        result.validation_errors = val_errors
        result.parse_status = "success" if result.schema_valid else val_status
        result.parse_error = None if result.schema_valid else "; ".join(val_errors)
        result.schema_normalization_applied = True
        result.recovery_type = "code_to_files_rename"
        steps.append("phase_g:SUCCESS(code_to_files_rename)")
    return result


# ============================================================
# LEGACY WRAPPER
# ============================================================


def parse_generation_v2(raw: str, condition: str) -> ParsedGenerationV2:
    """Legacy wrapper. Delegates to execution parser."""
    return parse_v2_execution(raw, condition)
