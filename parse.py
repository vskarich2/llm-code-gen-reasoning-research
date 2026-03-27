"""Code extraction and response parsing for T3 benchmark.

All type coercions and fallbacks are logged as warnings.
No silent empty-string defaults.
"""

import json
import logging
import re

log = logging.getLogger("t3.parse")

# Ensure warnings are visible even without logging config
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.WARNING)


# ============================================================
# JSON RESPONSE PARSING (3 tiers + orchestrator)
# ============================================================


def _try_json_direct(raw: str) -> dict | None:
    """Tier 1: Direct json.loads()."""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "code" in parsed:
            code = parsed.get("code")
            # "reasoning" is the standard field; "bug_diagnosis" is the
            # leg_reduction schema equivalent. Accept either.
            reasoning = parsed.get("reasoning")
            if reasoning is None and "bug_diagnosis" in parsed:
                reasoning = parsed.get("bug_diagnosis")

            # Type enforcement with SEVERE warnings
            if code is None:
                log.warning("SEVERE: JSON parsed but 'code' field is None")
                return None
            if isinstance(code, dict):
                # Model returned {"file1.py": "code1", "file2.py": "code2"}
                # Join values as separate code blocks
                log.warning(
                    "SEVERE: 'code' field is dict with %d keys (%s) — "
                    "joining values as code blocks",
                    len(code),
                    ", ".join(list(code.keys())[:4]),
                )
                code = "\n\n".join(
                    f"# {fname}\n{content}" if isinstance(content, str) else str(content)
                    for fname, content in code.items()
                )
            elif not isinstance(code, str):
                log.warning(
                    "SEVERE: 'code' field is %s (len=%d), not str — coercing",
                    type(code).__name__,
                    len(str(code)),
                )
                code = str(code)
            if reasoning is not None and not isinstance(reasoning, str):
                log.warning(
                    "SEVERE: 'reasoning' field is %s, not str — coercing", type(reasoning).__name__
                )
                reasoning = str(reasoning)
            if reasoning is None:
                log.warning("'reasoning' field is None — defaulting to empty string")
                reasoning = ""
            if not code.strip():
                log.warning("SEVERE: 'code' field is empty string after parsing")

            return {
                "reasoning": reasoning,
                "code": code,
                "confidence": parsed.get("confidence"),
                "parse_error": None,
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _try_json_lenient(raw: str) -> dict | None:
    """Tier 1b: Handle JSON with unescaped newlines in string values.

    Model often returns {"reasoning": "...", "code": "def f():\n    pass"}
    where the newlines inside the code string are literal, not escaped.
    """
    if not raw.strip().startswith("{") or '"code"' not in raw:
        return None

    # Try to extract reasoning and code by finding the field boundaries
    try:
        # Find "code" : " ... (everything to the last ")
        code_match = re.search(r'"code"\s*:\s*"(.*)"(?:\s*,\s*"confidence|\s*\})', raw, re.DOTALL)
        reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)"\s*,\s*"code"', raw, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            # Unescape basic sequences
            code = code.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            reasoning = ""
            if reasoning_match:
                reasoning = reasoning_match.group(1).replace("\\n", "\n").replace('\\"', '"')
            if code.strip():
                log.warning("Used lenient JSON parser for malformed response (len=%d)", len(raw))
                return {
                    "reasoning": reasoning,
                    "code": code,
                    "confidence": None,
                    "parse_error": "lenient-json: extracted from malformed JSON",
                }
    except Exception:
        pass
    return None


def _try_json_substring(raw: str) -> dict | None:
    """Tier 2: Extract JSON object containing 'code' key from mixed text."""
    m = re.search(r'\{[^{}]*"code"\s*:\s*".*?"[^{}]*\}', raw, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            code = parsed.get("code")
            reasoning = parsed.get("reasoning", "")
            if code is None or not isinstance(code, str):
                log.warning(
                    "SEVERE: JSON substring extracted but code=%r (type=%s)",
                    code,
                    type(code).__name__,
                )
                return None
            if not code.strip():
                log.warning("SEVERE: JSON substring code field is empty")
            return {
                "reasoning": str(reasoning) if reasoning else "",
                "code": code,
                "confidence": parsed.get("confidence"),
                "parse_error": None,
            }
        except json.JSONDecodeError:
            pass
    return None


def _try_code_block(raw: str) -> dict | None:
    """Tier 3: Extract from ```python code blocks."""
    blocks = re.findall(r"```python\s*\n(.*?)```", raw, re.DOTALL)
    if blocks:
        code = blocks[-1].strip()
        if not code:
            log.warning("SEVERE: found ```python block but it is empty")
            return None
        first_pos = raw.find("```python")
        reasoning = raw[:first_pos].strip() if first_pos > 0 else ""
        return {
            "reasoning": reasoning,
            "code": code,
            "confidence": None,
            "parse_error": "non-json: extracted from code block",
        }
    return None


def _try_file_dict(raw: str) -> dict | None:
    """Tier 0: JSON with 'files' dict (new multi-file format).

    Expected format: {"reasoning": "...", "files": {"path": "content|UNCHANGED"}}
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "files" in parsed:
            files = parsed["files"]
            if isinstance(files, dict) and all(isinstance(v, str) for v in files.values()):
                reasoning = parsed.get("reasoning", "")
                if reasoning is not None and not isinstance(reasoning, str):
                    reasoning = str(reasoning)
                return {
                    "reasoning": reasoning or "",
                    "code": None,
                    "files": files,
                    "confidence": parsed.get("confidence"),
                    "parse_error": None,
                    "response_format": "file_dict",
                }
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _try_file_dict_lenient(raw: str) -> dict | None:
    """Tier 0b: Handle file-dict JSON with literal newlines in string values.

    Models (especially nano) return {"reasoning": "...", "files": {"path": "code"}}
    with literal unescaped newlines inside the code strings. json.loads() rejects this.
    This tier extracts reasoning and files via regex, analogous to _try_json_lenient
    for code-key format.
    """
    if not raw.strip().startswith("{") or '"files"' not in raw:
        return None

    try:
        # Extract reasoning (before "files" key)
        reasoning = ""
        reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)"\s*,\s*"files"', raw, re.DOTALL)
        if reasoning_match:
            reasoning = reasoning_match.group(1).replace("\\n", "\n").replace('\\"', '"')

        # Extract the files dict content: everything between "files": { and the final }
        files_match = re.search(r'"files"\s*:\s*\{(.*)\}\s*\}', raw, re.DOTALL)
        if not files_match:
            return None

        files_content = files_match.group(1)

        # Parse individual file entries: "path": "content" or "path": "UNCHANGED"
        files = {}
        # Split on pattern: "path": "
        entries = re.finditer(
            r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', files_content, re.DOTALL
        )
        for m in entries:
            path = m.group(1)
            content = m.group(2)
            # Unescape JSON string escapes
            content = content.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            files[path] = content

        if not files:
            return None

        log.warning(
            "Used lenient file-dict parser for malformed response (len=%d, %d files)",
            len(raw),
            len(files),
        )
        return {
            "reasoning": reasoning,
            "code": None,
            "files": files,
            "confidence": None,
            "parse_error": "lenient-file-dict: extracted from malformed JSON",
            "response_format": "file_dict_lenient",
        }
    except Exception:
        pass
    return None


def _try_code_dict(raw: str) -> dict | None:
    """Tier 1a: JSON with 'code' as dict (model used code key for per-file output)."""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "code" in parsed and isinstance(parsed["code"], dict):
            files = parsed["code"]
            if all(isinstance(v, str) for v in files.values()):
                reasoning = parsed.get("reasoning", "")
                if reasoning is not None and not isinstance(reasoning, str):
                    reasoning = str(reasoning)
                log.info(
                    "code_dict response: 'code' key is dict with %d files (%s)",
                    len(files),
                    ", ".join(list(files.keys())[:4]),
                )
                return {
                    "reasoning": reasoning or "",
                    "code": None,
                    "files": files,
                    "confidence": parsed.get("confidence"),
                    "parse_error": None,
                    "response_format": "code_dict",
                }
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def parse_model_response(raw: str) -> dict:
    """Parse model response into {reasoning, code, files, confidence, parse_error, response_format}.

    Tiers: file_dict → code_dict → JSON direct → JSON lenient → JSON substring → code block → raw fallback.
    Never raises. Logs SEVERE warnings for type mismatches and empty fields.

    New fields added:
      - response_format: str identifying which parser tier succeeded
      - files: dict | None — per-file content when model returns file-dict format
    """
    if not raw or not raw.strip():
        log.warning("SEVERE: model returned empty response")
        return {
            "reasoning": "",
            "code": "",
            "files": None,
            "confidence": None,
            "parse_error": "SEVERE: empty model response",
            "response_format": "empty",
            # Observability fields (Phase 1)
            "code_present": False,
            "code_empty_reason": "model_no_output",
            "parse_tier": -1,
            "parse_repaired": False,
            "parse_repair_type": None,
            "data_lineage": ["raw_output_received", "parse_failed:empty_response"],
        }

    lineage = ["raw_output_received"]

    # Tier 0a: file-dict format (strict JSON)
    result = _try_file_dict(raw)
    if result:
        result["parse_tier"] = 0
        result["parse_repaired"] = False
        result["parse_repair_type"] = None
        # file_dict: code=None, code_present depends on reconstruction
        result["code_present"] = False
        result["code_empty_reason"] = None  # set after reconstruction
        lineage.append("parse_tier_0a_file_dict_matched")
        result["data_lineage"] = lineage
        return result

    # Tier 0b: file-dict format (lenient — handles literal newlines in strings)
    result = _try_file_dict_lenient(raw)
    if result:
        result["parse_tier"] = 1
        result["parse_repaired"] = True
        result["parse_repair_type"] = "lenient_file_dict"
        result["code_present"] = False
        result["code_empty_reason"] = None
        lineage.append("parse_tier_0b_file_dict_lenient_matched")
        lineage.append("parse_repair:lenient_file_dict")
        result["data_lineage"] = lineage
        return result

    # Tier 1a: code-as-dict (model put per-file dict in "code" key)
    result = _try_code_dict(raw)
    if result:
        result["parse_tier"] = 2
        result["parse_repaired"] = False
        result["parse_repair_type"] = None
        result["code_present"] = False
        result["code_empty_reason"] = None
        lineage.append("parse_tier_1a_code_dict_matched")
        result["data_lineage"] = lineage
        return result

    # Tier 1b: direct JSON with code-as-string
    result = _try_json_direct(raw)
    if result:
        result["response_format"] = "json_direct"
        result.setdefault("files", None)
        result["parse_tier"] = 3
        result["parse_repaired"] = False
        result["parse_repair_type"] = None
        code = result.get("code", "")
        result["code_present"] = bool(code and code.strip() and len(code.strip()) >= 10)
        result["code_empty_reason"] = None if result["code_present"] else "no_code_field"
        lineage.append("parse_tier_1b_json_direct_matched")
        result["data_lineage"] = lineage
        return result

    # Tier 1c: lenient JSON
    result = _try_json_lenient(raw)
    if result:
        result["response_format"] = "json_lenient"
        result.setdefault("files", None)
        result["parse_tier"] = 4
        result["parse_repaired"] = True
        result["parse_repair_type"] = "lenient_json"
        code = result.get("code", "")
        result["code_present"] = bool(code and code.strip() and len(code.strip()) >= 10)
        result["code_empty_reason"] = None if result["code_present"] else "parse_failure"
        lineage.append("parse_tier_1c_json_lenient_matched")
        lineage.append("parse_repair:lenient_json")
        result["data_lineage"] = lineage
        return result

    # Tier 2: JSON substring
    result = _try_json_substring(raw)
    if result:
        result["response_format"] = "json_substring"
        result.setdefault("files", None)
        result["parse_tier"] = 5
        result["parse_repaired"] = False
        result["parse_repair_type"] = None
        code = result.get("code", "")
        result["code_present"] = bool(code and code.strip() and len(code.strip()) >= 10)
        result["code_empty_reason"] = None if result["code_present"] else "parse_failure"
        lineage.append("parse_tier_2_json_substring_matched")
        result["data_lineage"] = lineage
        return result

    # Tier 3: code block
    result = _try_code_block(raw)
    if result:
        result["response_format"] = "code_block"
        result.setdefault("files", None)
        result["parse_tier"] = 6
        result["parse_repaired"] = False
        result["parse_repair_type"] = None
        code = result.get("code", "")
        result["code_present"] = bool(code and code.strip() and len(code.strip()) >= 10)
        result["code_empty_reason"] = None if result["code_present"] else "parse_failure"
        lineage.append("parse_tier_3_code_block_matched")
        result["data_lineage"] = lineage
        return result

    # Tier 4: Raw fallback — ALL downstream consumers MUST see this flag
    log.warning(
        "RAW FALLBACK: No JSON or code blocks found in model output (len=%d). "
        "Using raw text as code. This is NOT a model code failure — "
        "this is a PARSE failure. First 100 chars: %r",
        len(raw),
        raw[:100],
    )
    lineage.append("parse_tier_4_raw_fallback")
    return {
        "reasoning": "",
        "code": raw.strip(),
        "files": None,
        "confidence": None,
        "parse_error": "SEVERE: raw_fallback — no code blocks found, entire response used as code",
        "_raw_fallback": True,
        "response_format": "raw_fallback",
        "code_present": False,
        "code_empty_reason": "filtered_invalid",
        "parse_tier": 7,
        "parse_repaired": False,
        "parse_repair_type": None,
        "data_lineage": lineage,
    }


# ============================================================
# STRICT JSON PARSER (v3 — sanitized extraction, no semantic parsing)
# ============================================================

_REQUIRED_KEYS = ("reasoning", "plan", "code")


def _extract_json_block(raw: str) -> str:
    """Extract the first JSON object from raw text.

    Transport-layer cleanup ONLY:
    - Removes ```json / ``` markdown fences
    - Finds first { and matches to closing }
    - No semantic parsing, no field extraction, no content modification

    Raises ValueError if no valid JSON object found.
    """
    text = raw.strip()

    # Remove markdown fences (transport artifact, not content)
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Find first JSON object via bracket matching
    start = text.find("{")
    if start == -1:
        raise ValueError("NO_JSON_OBJECT_FOUND")

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
                return text[start : i + 1]

    raise ValueError("UNBALANCED_JSON")


def parse_structured_output(raw: str) -> dict:
    """Strict JSON parser with sanitized extraction. No semantic fallback.

    Pipeline:
    1. Extract JSON block (strip markdown fences, find { ... })
    2. json.loads() — no recovery on failure
    3. Validate required keys and types

    Returns: {
        "reasoning": str,
        "plan": list[str],
        "code": str,
        "confidence": float|None,
        "parse_error": str|None,
        "valid_schema": bool,
    }
    """
    result = {
        "reasoning": "",
        "plan": [],
        "code": "",
        "confidence": None,
        "parse_error": None,
        "valid_schema": False,
    }

    if not raw or not raw.strip():
        result["parse_error"] = "empty_response"
        return result

    # Step 1: Extract JSON block (transport-layer cleanup only)
    try:
        json_str = _extract_json_block(raw)
    except ValueError as e:
        result["parse_error"] = f"extraction_error: {e}"
        return result

    # Step 2: Parse JSON — no fallback
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        result["parse_error"] = f"json_decode_error: {e}"
        return result

    if not isinstance(parsed, dict):
        result["parse_error"] = f"not_a_dict: got {type(parsed).__name__}"
        return result

    # Step 3: Validate required keys
    for key in _REQUIRED_KEYS:
        if key not in parsed:
            result["parse_error"] = f"missing_key: {key}"
            return result

    # Step 4: Type validation
    reasoning = parsed["reasoning"]
    plan = parsed["plan"]
    code = parsed["code"]

    if not isinstance(reasoning, str):
        result["parse_error"] = f"reasoning_not_str: got {type(reasoning).__name__}"
        return result

    if not isinstance(plan, list):
        result["parse_error"] = f"plan_not_list: got {type(plan).__name__}"
        return result

    if not all(isinstance(s, str) for s in plan):
        result["parse_error"] = "plan_contains_non_str"
        return result

    if not isinstance(code, str):
        result["parse_error"] = f"code_not_str: got {type(code).__name__}"
        return result

    # Success
    result["reasoning"] = reasoning
    result["plan"] = plan
    result["code"] = code
    result["confidence"] = (
        parsed.get("metadata", {}).get("confidence")
        if isinstance(parsed.get("metadata"), dict)
        else parsed.get("confidence")
    )
    result["valid_schema"] = True
    return result


# ============================================================
# CODE EXTRACTION (legacy — used by exec_eval)
# ============================================================


def extract_code(output: str) -> str:
    """Extract the last ```python block. Falls back to raw text."""
    blocks = re.findall(r"```python\s*\n(.*?)```", output, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    blocks = re.findall(r"```\s*\n(.*?)```", output, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    log.warning("extract_code: no code blocks found, returning raw (len=%d)", len(output))
    return output.strip()


def extract_all_code_blocks(output: str) -> list[tuple[str, str]]:
    """Extract all (filename_hint, code) pairs from model output."""
    blocks = []
    for m in re.finditer(
        r"(?:#\s*(\S+\.py)[^\n]*\n)?```python\s*\n(.*?)```",
        output,
        re.DOTALL,
    ):
        name = m.group(1) or f"block_{len(blocks)}.py"
        blocks.append((name, m.group(2).strip()))
    if not blocks:
        code = extract_code(output)
        if code:
            blocks.append(("candidate.py", code))
    return blocks


# ============================================================
# IMPORT STRIPPING
# ============================================================

from _stdlib import STDLIB_MODULES


def strip_local_imports(code: str) -> str:
    """Remove import statements that reference sibling modules.

    Preserves stdlib imports. Handles multi-line from X import (...) blocks.
    """
    # Pass 1: multi-line local imports
    code = re.sub(
        r"^from\s+(?!(?:"
        + "|".join(re.escape(m) for m in STDLIB_MODULES)
        + r")\b)\w+\s+import\s*\(.*?\)",
        "",
        code,
        flags=re.MULTILINE | re.DOTALL,
    )

    # Pass 2: single-line local imports
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("from .", "import .")):
            continue
        if stripped.startswith("from ") and " import " in stripped:
            mod = stripped.split("from ", 1)[1].split(" import")[0].strip()
            if "." not in mod and mod not in STDLIB_MODULES:
                continue
        elif stripped.startswith("import "):
            mod = stripped.split("import ", 1)[1].split()[0].strip().rstrip(",")
            if mod not in STDLIB_MODULES:
                continue
        lines.append(line)
    return "\n".join(lines)
