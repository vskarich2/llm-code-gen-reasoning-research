"""Code extraction and response parsing for T3 benchmark.

All type coercions and fallbacks are logged as warnings.
No silent empty-string defaults.

Reasoning schema v2: every parse result includes reasoning_obj and
reasoning_validation, extracted from the already-parsed JSON at the
orchestrator level. No re-parsing. No fallbacks.
"""

import json
import logging
import re

from reasoning import extract_reasoning_obj, validate_reasoning

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
                "_raw_json": parsed,
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
                    "_raw_json": None,
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
                "_raw_json": parsed,
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
            "_raw_json": None,
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
                    "_raw_json": parsed,
                }
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _try_file_dict_lenient(raw: str) -> dict | None:
    """Tier 0b: Handle file-dict JSON with malformed string values.

    Models (especially nano) produce JSON with unescaped quotes, literal newlines,
    or triple-quoted Python docstrings inside string values. json.loads() rejects this.

    Strategy: find "files": { ... } region, then for each file entry, extract the
    content between the opening quote after the colon and the closing pattern
    (either '", "next_path"' or '"}}' at end). This handles unescaped quotes
    inside the content because we anchor on structural delimiters, not quote matching.
    """
    if not raw.strip().startswith("{") or '"files"' not in raw:
        return None

    try:
        # Extract the files region: from "files": { to the final }}
        files_match = re.search(r'"files"\s*:\s*\{(.*)\}\s*\}', raw, re.DOTALL)
        if not files_match:
            return None

        files_content = files_match.group(1)

        # Find all file paths: "path/to/file.py": "
        # Then extract content between that opening quote and the next file entry or end
        path_pattern = re.compile(r'"([^"]+\.(?:py|txt|json|yaml|yml|md|cfg|ini|toml))"\s*:\s*"')
        path_matches = list(path_pattern.finditer(files_content))

        if not path_matches:
            return None

        files = {}
        for i, pm in enumerate(path_matches):
            path = pm.group(1)
            content_start = pm.end()  # position right after the opening quote

            if i + 1 < len(path_matches):
                # Content ends before the next file entry: look for '", "next_path"'
                # Scan backwards from next match to find the closing '"'
                next_start = path_matches[i + 1].start()
                # The content region is between content_start and the last '"' before next entry
                region = files_content[content_start:next_start]
                # Strip trailing '", ' or '",\n'
                region = region.rstrip()
                if region.endswith('",'):
                    region = region[:-2]
                elif region.endswith('"'):
                    region = region[:-1]
            else:
                # Last file: content ends at the closing quote before }}
                region = files_content[content_start:]
                region = region.rstrip()
                if region.endswith('"'):
                    region = region[:-1]

            # Unescape JSON string escapes
            content = region.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            files[path] = content

        if not files:
            return None

        # Extract reasoning fields from the text before "files"
        reasoning = ""
        reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)"\s*,\s*"files"', raw, re.DOTALL)
        if reasoning_match:
            reasoning = reasoning_match.group(1).replace("\\n", "\n").replace('\\"', '"')

        # Also try to extract structured reasoning fields for _raw_json
        raw_json = None
        for field in ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy",
                       "risk_check"):
            m = re.search(rf'"{field}"\s*:\s*"(.*?)"\s*,\s*"', raw, re.DOTALL)
            if m:
                if raw_json is None:
                    raw_json = {}
                raw_json[field] = m.group(1).replace("\\n", "\n").replace('\\"', '"')

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
            "_raw_json": raw_json,
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
                    "_raw_json": parsed,
                }
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _apply_reasoning_extraction(result):
    """Extract reasoning_obj and reasoning_validation from parse result.

    Uses _raw_json (the already-parsed JSON dict stashed by the tier).
    If _raw_json is None (non-JSON tier), reasoning fields are empty.
    Mutates result in place. Called ONCE per parse at the orchestrator level.
    """
    raw_json = result.get("_raw_json")
    if raw_json is not None and isinstance(raw_json, dict):
        result["reasoning_obj"] = extract_reasoning_obj(raw_json)
        result["reasoning_validation"] = validate_reasoning(result["reasoning_obj"], raw_json)
    else:
        result["reasoning_obj"] = extract_reasoning_obj({})
        result["reasoning_validation"] = validate_reasoning(result["reasoning_obj"], {})


def parse_model_response(raw):
    """Parse model response. Single entry point for ALL response parsing.

    Returns dict with: reasoning, code, files, confidence, parse_error,
    response_format, reasoning_obj, reasoning_validation, and observability fields.

    reasoning_obj and reasoning_validation are ALWAYS present (schema v2).
    """
    result = _parse_model_response_tiers(raw)
    _apply_reasoning_extraction(result)
    return result


def _parse_model_response_tiers(raw):
    """Internal: tier-based parsing. Returns result with _raw_json stashed.

    Tiers: file_dict → code_dict → JSON direct → JSON lenient → JSON substring → code block → raw fallback.
    Never raises. Logs SEVERE warnings for type mismatches and empty fields.
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
            "_raw_json": None,
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
        "_raw_json": None,
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


def classify_import(module_name: str, case_local_modules: frozenset | None = None) -> str:
    """Classify an import as 'stdlib', 'local', or 'unknown'.

    Args:
        module_name: the imported module name (e.g., 'config', 'os', 'decimal')
        case_local_modules: set of known local module names for the current case.
            If None, any non-stdlib module is treated as local.

    Returns: 'stdlib', 'local', or 'unknown'
    """
    if module_name in STDLIB_MODULES:
        return "stdlib"
    if case_local_modules is not None:
        if module_name in case_local_modules:
            return "local"
        return "unknown"
    # No case context — treat all non-stdlib as local (backward compat for assembly)
    return "local"


def strip_local_imports(code: str, case_local_modules: frozenset | None = None,
                         strict: bool = False) -> str:
    """Remove import statements that reference sibling modules.

    Preserves stdlib imports. Strips local (sibling) imports since all code
    is concatenated into one module during assembly.

    Args:
        code: source code to process
        case_local_modules: known local module names. If provided, enables strict mode.
        strict: if True, raise RuntimeError on unknown imports instead of stripping.

    Raises:
        RuntimeError: if strict=True and an unknown (non-stdlib, non-local) import is found.
    """
    # Pass 1: multi-line local imports (from X import (...))
    code = re.sub(
        r"^from\s+(?!(?:"
        + "|".join(re.escape(m) for m in STDLIB_MODULES)
        + r")\b)\w+\s+import\s*\(.*?\)",
        "",
        code,
        flags=re.MULTILINE | re.DOTALL,
    )

    # Pass 2: single-line imports
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()

        # Relative imports → always strip (local)
        if stripped.startswith(("from .", "import .")):
            continue

        # from X import Y
        if stripped.startswith("from ") and " import " in stripped:
            mod = stripped.split("from ", 1)[1].split(" import")[0].strip()
            base_mod = mod.split(".")[0] if "." in mod else mod
            classification = classify_import(base_mod, case_local_modules)

            if classification == "stdlib":
                lines.append(line)
                continue
            elif classification == "local":
                continue  # strip local imports
            else:
                if strict:
                    raise RuntimeError(
                        f"Unknown import in model code: 'from {mod} import ...' — "
                        f"module '{base_mod}' is not in STDLIB_MODULES and not a known "
                        f"case-local module. Add to _stdlib.py if it is a stdlib module, "
                        f"or investigate why the model imported it."
                    )
                continue  # non-strict: strip like local

        # import X
        elif stripped.startswith("import "):
            mod = stripped.split("import ", 1)[1].split()[0].strip().rstrip(",")
            classification = classify_import(mod, case_local_modules)

            if classification == "stdlib":
                lines.append(line)
                continue
            elif classification == "local":
                continue
            else:
                if strict:
                    raise RuntimeError(
                        f"Unknown import in model code: 'import {mod}' — "
                        f"module '{mod}' is not in STDLIB_MODULES and not a known "
                        f"case-local module."
                    )
                continue

        else:
            lines.append(line)

    return "\n".join(lines)
