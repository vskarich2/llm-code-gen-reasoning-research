"""V2 generation output parser — SOLE JSON deserializer for v2 outputs.

This module is the ONE AND ONLY authority for deserializing v2 generation responses.
No downstream v2 code may call json.loads() on raw response text.
No delegation to parse_model_response().

Parse pipeline:
1. Strip markdown fences if present
2. Find first balanced JSON block via bracket matching
3. json.loads() exactly once
4. Validate against schema contract
5. Return ParsedGenerationV2
"""

import json
import logging
import re
from dataclasses import dataclass, field

from contracts_v2 import validate_generation_fields, CONDITION_TO_SCHEMA

_log = logging.getLogger("t3.parser_v2")


@dataclass
class ParsedGenerationV2:
    """Canonical parsed v2 generation output. Produced ONLY by parse_generation_v2()."""
    parse_status: str              # "success" | "partial" | "failed"
    schema_variant: str            # "baseline_v2" | "leg_v2" | "lean_v2"
    full_json: dict | None         # complete parsed JSON — AUTHORITATIVE
    files_dict: dict | None        # extracted files dict
    parse_error: str | None        # specific error if parse_status != "success"
    raw_response_text: str         # original raw string (for logging only, NOT for reparsing)
    parser_variant: str = "parser_v2_generation"
    validation_status: str = ""    # "valid" | "partial" | "invalid" — from contract validation
    validation_errors: list[str] = field(default_factory=list)


def _strip_fences(text: str) -> str:
    """Strip markdown code fences if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1:]
        else:
            stripped = ""
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _find_json_block(text: str) -> str | None:
    """Find first balanced JSON object via bracket matching."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\" and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _repair_triple_quotes(text: str) -> tuple[str, bool]:
    """Repair unescaped Python code in JSON file content values.

    LLMs (especially nano) output Python files containing triple-quote
    docstrings directly into JSON string values without escaping.

    Returns (repaired_text, was_repaired).
    """
    try:
        json.loads(text)
        return text, False
    except (json.JSONDecodeError, TypeError):
        pass

    # Find file content values and re-encode them properly.
    # Pattern: "filepath.py": "...code..." where the code contains unescaped quotes.
    # We find each file key, extract its raw value text, and re-escape.

    files_match = re.search(r'"files"\s*:\s*\{', text)
    if not files_match:
        return text, False

    prefix = text[:files_match.end()]
    rest = text[files_match.end():]

    key_pattern = re.compile(r'"([^"]+\.py)"\s*:\s*')
    keys = list(key_pattern.finditer(rest))
    if not keys:
        return text, False

    # Reconstruct: prefix + rebuilt files dict + outer closing
    rebuilt_entries = []
    repaired = False

    for idx, key_m in enumerate(keys):
        filepath = key_m.group(1)
        val_start = key_m.end()

        # Value extends to the start of the next key or to end of rest
        if idx + 1 < len(keys):
            val_region_end = keys[idx + 1].start()
        else:
            # Last entry — find its end by looking for the pattern:
            # closing quote + optional whitespace + } (end of files dict)
            # Search from the end of rest backwards
            val_region_end = len(rest)

        val_region = rest[val_start:val_region_end].strip()
        # Strip trailing comma
        if val_region.endswith(','):
            val_region = val_region[:-1].strip()
        # Strip trailing closing braces (files dict + outer JSON)
        while val_region.endswith('}'):
            val_region = val_region[:-1].strip()

        # Try as valid JSON string first
        try:
            val = json.loads(val_region)
            rebuilt_entries.append(f'"{filepath}": {json.dumps(val)}')
            continue
        except (json.JSONDecodeError, TypeError):
            pass

        # Extract raw content and re-escape quotes
        if val_region.startswith('"') and val_region.endswith('"') and len(val_region) > 2:
            raw_content = val_region[1:-1]
        elif val_region.startswith('"'):
            raw_content = val_region[1:]
        elif val_region.startswith('\\'):
            raw_content = val_region
        else:
            return text, False

        # Escape unescaped double-quotes (model escaped \n but not ")
        fixed = re.sub(r'(?<!\\)"', r'\\"', raw_content)
        rebuilt_entries.append(f'"{filepath}": "{fixed}"')
        repaired = True

    if not repaired:
        return text, False

    # Rebuild: everything before "files": { + entries + closing
    files_body = ',\n    '.join(rebuilt_entries)
    # Count closing braces needed: one for files dict, rest from original
    # Find how the original text ends after the files section
    outer_suffix = '\n  }\n}'
    candidate = prefix + '\n    ' + files_body + outer_suffix

    try:
        json.loads(candidate)
        _log.info("parser_v2: JSON repair succeeded (triple-quote escaping)")
        return candidate, True
    except (json.JSONDecodeError, TypeError):
        _log.debug("parser_v2: repair assembled but still invalid")

    return text, False


def parse_generation_v2(raw_response_text: str, condition: str) -> ParsedGenerationV2:
    """Parse a v2 generation response. SOLE JSON deserializer for v2.

    Args:
        raw_response_text: raw model response string
        condition: condition name (e.g., "baseline_v2", "leg_reduction_v2")

    Returns:
        ParsedGenerationV2 with parse_status, full_json, files_dict, validation.
    """
    schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)

    if not raw_response_text or not raw_response_text.strip():
        return ParsedGenerationV2(
            parse_status="failed",
            schema_variant=schema_variant,
            full_json=None,
            files_dict=None,
            parse_error="empty response",
            raw_response_text=raw_response_text or "",
        )

    # Step 1: strip markdown fences
    cleaned = _strip_fences(raw_response_text)

    # Step 2: find JSON block
    json_str = _find_json_block(cleaned)
    if json_str is None:
        json_str = _find_json_block(raw_response_text)

    # Step 3: json.loads() — exactly once (with repair on failure)
    parsed = None
    parse_error_msg = None

    if json_str is not None:
        try:
            parsed = json.loads(json_str)
        except (json.JSONDecodeError, TypeError) as e:
            parse_error_msg = str(e)

    # Step 3b: If direct parse failed (or no block found), try repair on full text
    if parsed is None:
        repaired_str, was_repaired = _repair_triple_quotes(cleaned)
        if was_repaired:
            try:
                parsed = json.loads(repaired_str)
                parse_error_msg = None
            except (json.JSONDecodeError, TypeError) as e2:
                parse_error_msg = f"JSON decode error (after repair): {e2}"

    if parsed is None:
        return ParsedGenerationV2(
            parse_status="failed",
            schema_variant=schema_variant,
            full_json=None,
            files_dict=None,
            parse_error=parse_error_msg or "no JSON object found",
            raw_response_text=raw_response_text,
        )

    if not isinstance(parsed, dict):
        return ParsedGenerationV2(
            parse_status="failed",
            schema_variant=schema_variant,
            full_json=None,
            files_dict=None,
            parse_error=f"parsed value is {type(parsed).__name__}, not dict",
            raw_response_text=raw_response_text,
        )

    # Step 4: extract files_dict
    files_dict = None
    if "files" in parsed and isinstance(parsed["files"], dict):
        files_dict = parsed["files"]

    # Step 5: validate against schema contract
    val_status, val_errors = validate_generation_fields(parsed, schema_variant)

    parse_status = "success" if val_status == "valid" else val_status

    if val_errors:
        _log.info("parser_v2 validation for %s: %s — %s", schema_variant, val_status, val_errors)

    return ParsedGenerationV2(
        parse_status=parse_status,
        schema_variant=schema_variant,
        full_json=parsed,
        files_dict=files_dict,
        parse_error=None if parse_status == "success" else "; ".join(val_errors),
        raw_response_text=raw_response_text,
        validation_status=val_status,
        validation_errors=val_errors,
    )
