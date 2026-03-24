"""Contract-Gated Execution — Diff Gate.

Validates candidate code against an Execution Contract.
Six check categories, all rule-based and deterministic.
"""

import re
import logging

log = logging.getLogger("t3.diff_gate")


# ============================================================
# OPERATION ALIAS SETS
# ============================================================

OPERATION_ALIASES = {
    "commit": ["commit(", "session.commit(", "tx.commit(", "db.commit(", ".save(", ".flush("],
    "write_cache": ["cache_put(", "cache_set(", "_store[", "write_cache(", "sync_user_to_cache(", "update_cache("],
    "debit": ["balance -=", "balance -", ".charge(", "withdraw(", ".debit("],
    "credit": ["balance +=", "balance +", ".credit(", ".refund(", "deposit("],
    "insert": ["insert(", ".append(", "upsert(", "apply_delta(", "_records["],
    "delete": ["delete(", "remove(", "invalidate(", "cache_delete(", "pop("],
    "lock": ["try_lock(", "acquire(", ".lock("],
    "unlock": ["unlock(", "release(", ".unlock("],
    "log_op": ["record_", "emit_", "log_", "_log.append("],
    "stage": ["stage("],
    "freeze": ["freeze_view("],
}


# ============================================================
# MAIN VALIDATE
# ============================================================

def validate(contract: dict, code: str, reference_code: str) -> dict:
    """Run all 6 check categories against candidate code.

    Returns {"valid": bool, "violations": [...], "checks_run": int, "checks_passed": int}
    """
    violations = []
    checks_run = 0
    checks_passed = 0

    for checker in [
        _check_must_change,
        _check_must_not_change,
        _check_required_effects,
        _check_ordering,
        _check_retry_safety,
        _check_rollback,
    ]:
        passed, v = checker(contract, code, reference_code)
        checks_run += 1
        if passed:
            checks_passed += 1
        violations.extend(v)

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "checks_run": checks_run,
        "checks_passed": checks_passed,
    }


# ============================================================
# CHECK 1: must_change — structural
# ============================================================

def _check_must_change(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []
    for target in contract.get("must_change", []):
        symbol = target.split("::")[-1].strip()
        if f"def {symbol}" not in code and f"class {symbol}" not in code:
            violations.append(f"STRUCTURAL: must_change target '{symbol}' not found in output")
    return len(violations) == 0, violations


# ============================================================
# CHECK 2: must_not_change — structural (body comparison)
# ============================================================

def _check_must_not_change(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []
    for target in contract.get("must_not_change", []):
        symbol = target.split("::")[-1].strip()
        ref_body = _extract_function_body(ref, symbol)
        cand_body = _extract_function_body(code, symbol)
        if cand_body is None:
            continue  # not redefined — acceptable
        if ref_body is None:
            continue  # can't compare without reference
        if _normalize_body(cand_body) != _normalize_body(ref_body):
            violations.append(f"STRUCTURAL: must_not_change target '{symbol}' was modified")
    return len(violations) == 0, violations


def _extract_function_body(code: str, name: str) -> str | None:
    """Extract the body of def {name}(...): from code."""
    pattern = rf"^([ \t]*)def {re.escape(name)}\s*\("
    lines = code.split("\n")
    start = None
    base_indent = 0
    for i, line in enumerate(lines):
        m = re.match(pattern, line)
        if m:
            start = i
            base_indent = len(m.group(1))
            break
    if start is None:
        return None
    body_lines = [lines[start]]
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() == "":
            body_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and line.strip():
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def _normalize_body(body: str) -> str:
    """Normalize whitespace for comparison."""
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    return "\n".join(lines)


# ============================================================
# CHECK 3: required_effects — pattern detection
# ============================================================

_EFFECT_DETECTORS = {}


def _effect_detector(name):
    def decorator(fn):
        _EFFECT_DETECTORS[name] = fn
        return fn
    return decorator


def _check_required_effects(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []
    for effect in contract.get("required_effects", []):
        detector = _EFFECT_DETECTORS.get(effect)
        if detector is None:
            log.warning("No detector for required_effect '%s' — skipping", effect)
            continue
        ok, msg = detector(contract, code)
        if not ok and msg:
            violations.append(msg)
    return len(violations) == 0, violations


@_effect_detector("introduce_idempotency_guard")
def _detect_idempotency_guard(contract: dict, code: str) -> tuple[bool, str | None]:
    """Check that state-mutating calls have a guard (if X in Y / if not exists)."""
    mutating = contract.get("retry_semantics", {}).get("duplicate_effects_forbidden", [])
    if not mutating:
        mutating = ["insert(", "append(", "apply_delta("]
    code_lower = code.lower()
    for op in mutating:
        if op.lower() not in code_lower:
            continue
        # Found the operation — check for a guard above it
        lines = code.split("\n")
        for i, line in enumerate(lines):
            if op in line:
                guard = _scan_for_guard(lines, max(0, i - 10), i)
                if not guard:
                    return False, f"EFFECT: no idempotency guard before '{op}' at line {i+1}"
    return True, None


@_effect_detector("prevent_duplicate_effect")
def _detect_prevent_duplicate(contract: dict, code: str) -> tuple[bool, str | None]:
    """Check forbidden effects in loops have guards."""
    forbidden = contract.get("retry_semantics", {}).get("duplicate_effects_forbidden", [])
    lines = code.split("\n")
    for fn_name in forbidden:
        pattern = f"{fn_name}("
        for i, line in enumerate(lines):
            if pattern not in line:
                continue
            loop_start = _scan_backwards_for_loop(lines, i, 15)
            if loop_start is None:
                continue
            guard = _scan_for_guard(lines, loop_start, i)
            if not guard:
                return False, f"RETRY_SAFETY: '{fn_name}' called inside loop at line {i+1} without idempotency guard"
    return True, None


@_effect_detector("add_rollback_on_failure")
def _detect_rollback(contract: dict, code: str) -> tuple[bool, str | None]:
    """Check that rollback conditions have try/except with compensating logic."""
    conditions = contract.get("rollback_semantics", {}).get("must_rollback_if", [])
    if not conditions:
        # Generic check: any debit-like operation must have try/except
        if _has_operation(code, "debit") and "try:" not in code:
            return False, "ROLLBACK: debit-like operation found but no try/except block"
        return True, None
    for cond in conditions:
        ops = _extract_operation_pair(cond)
        if ops is None:
            continue
        first_op, second_op = ops
        first_lines = _find_operation_lines(code, first_op)
        if not first_lines:
            continue
        # Check for try/except
        lines = code.split("\n")
        has_try = False
        has_compensate = False
        for i, line in enumerate(lines):
            if "try:" in line:
                has_try = True
            if has_try and "except" in line.strip()[:8]:
                # Scan except block for compensation
                for j in range(i + 1, min(len(lines), i + 10)):
                    if any(p in lines[j] for p in ["+=", "release(", "refund(", "rollback(", "restore", "revert", "undo"]):
                        has_compensate = True
                        break
        if not has_try:
            return False, f"ROLLBACK: no try/except protecting window for condition '{cond}'"
        if not has_compensate:
            return False, f"ROLLBACK: except block has no compensating action for condition '{cond}'"
    return True, None


@_effect_detector("preserve_effect_order")
def _detect_preserve_order(contract: dict, code: str) -> tuple[bool, str | None]:
    """Delegates to the ordering check."""
    _, violations = _check_ordering(contract, code, "")
    if violations:
        return False, violations[0]
    return True, None


@_effect_detector("guard_side_effect")
def _detect_guard_side_effect(contract: dict, code: str) -> tuple[bool, str | None]:
    """Check that side effect calls are preceded by a conditional guard."""
    for se in contract.get("side_effects", []):
        effect = se.get("effect", "")
        lines = code.split("\n")
        effect_lines = _find_operation_lines(code, effect)
        for ln in effect_lines:
            guarded = False
            for j in range(max(0, ln - 5), ln):
                if lines[j].strip().startswith("if "):
                    guarded = True
                    break
            if not guarded:
                return False, f"EFFECT: side effect '{effect}' at line {ln+1} has no guard"
    return True, None


@_effect_detector("defer_side_effect_until_success")
def _detect_defer_until_success(contract: dict, code: str) -> tuple[bool, str | None]:
    """Check that deferred side effects occur after the success path."""
    for se in contract.get("side_effects", []):
        if se.get("when") != "after":
            continue
        effect = se.get("effect", "")
        anchor = se.get("relative_to", "")
        effect_lines = _find_operation_lines(code, effect)
        anchor_lines = _find_operation_lines(code, anchor)
        if not effect_lines or not anchor_lines:
            continue
        if min(effect_lines) <= max(anchor_lines):
            return False, f"EFFECT: '{effect}' must be deferred until after '{anchor}' succeeds"
    return True, None


# ============================================================
# CHECK 4: ordering constraints
# ============================================================

def _check_ordering(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []
    for se in contract.get("side_effects", []):
        effect = se.get("effect", "")
        anchor = se.get("relative_to", "")
        direction = se.get("when", "")

        if not effect or not anchor or direction not in ("before", "after"):
            continue

        effect_lines = _find_operation_lines(code, effect)
        anchor_lines = _find_operation_lines(code, anchor)

        if not anchor_lines:
            continue  # unresolvable
        if not effect_lines:
            violations.append(f"ORDERING: '{effect}' not found in code")
            continue

        if direction == "after":
            if min(effect_lines) <= max(anchor_lines):
                violations.append(
                    f"ORDERING: '{effect}' at line {min(effect_lines)+1} must occur "
                    f"after '{anchor}' at line {max(anchor_lines)+1}"
                )
        elif direction == "before":
            if max(effect_lines) >= min(anchor_lines):
                violations.append(
                    f"ORDERING: '{effect}' at line {max(effect_lines)+1} must occur "
                    f"before '{anchor}' at line {min(anchor_lines)+1}"
                )

    return len(violations) == 0, violations


# ============================================================
# CHECK 5: retry safety
# ============================================================

def _check_retry_safety(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []
    forbidden = contract.get("retry_semantics", {}).get("duplicate_effects_forbidden", [])
    lines = code.split("\n")
    for fn_name in forbidden:
        pattern = f"{fn_name}("
        for i, line in enumerate(lines):
            if pattern not in line:
                continue
            loop_start = _scan_backwards_for_loop(lines, i, 15)
            if loop_start is None:
                continue
            guard = _scan_for_guard(lines, loop_start, i)
            if not guard:
                violations.append(
                    f"RETRY_SAFETY: '{fn_name}' called inside loop at line {i+1} "
                    f"without idempotency guard"
                )
    return len(violations) == 0, violations


# ============================================================
# CHECK 6: rollback
# ============================================================

def _check_rollback(contract: dict, code: str, ref: str) -> tuple[bool, list[str]]:
    violations = []

    # Check must_rollback_if conditions
    for cond in contract.get("rollback_semantics", {}).get("must_rollback_if", []):
        ops = _extract_operation_pair(cond)
        if ops is None:
            continue
        first_op, second_op = ops
        first_lines = _find_operation_lines(code, first_op)
        second_lines = _find_operation_lines(code, second_op)
        if not first_lines or not second_lines:
            continue
        lines = code.split("\n")
        window_start = min(first_lines)
        window_end = max(second_lines)
        try_found = _find_enclosing_try(lines, window_start, window_end)
        if not try_found:
            violations.append(
                f"ROLLBACK: no try/except protecting window between '{first_op}' "
                f"(line {window_start+1}) and '{second_op}' (line {window_end+1})"
            )
            continue
        except_body = _extract_except_body(lines, try_found)
        compensating = ["+=", "release(", "refund(", "rollback(", "restore", "revert", "undo"]
        if not any(p in except_body for p in compensating):
            violations.append(
                f"ROLLBACK: except block after '{first_op}' has no compensating action"
            )

    # Check must_not_persist
    for operation in contract.get("rollback_semantics", {}).get("must_not_persist_after_failure", []):
        op_name = _extract_op_name(operation)
        op_lines = _find_operation_lines(code, op_name)
        if not op_lines:
            continue
        lines = code.split("\n")
        for ln in op_lines:
            if not _find_enclosing_try(lines, ln, ln):
                violations.append(
                    f"ROLLBACK: '{operation}' at line {ln+1} can persist after failure — no error handling"
                )
                break

    return len(violations) == 0, violations


# ============================================================
# HELPERS
# ============================================================

def _find_operation_lines(code: str, op_name: str) -> list[int]:
    """Find all line numbers where an operation appears (via aliases)."""
    patterns = OPERATION_ALIASES.get(op_name, [f"{op_name}("])
    lines = code.split("\n")
    found = []
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            continue
        for pat in patterns:
            if pat in line:
                found.append(i)
                break
    return sorted(set(found))


def _has_operation(code: str, op_name: str) -> bool:
    return len(_find_operation_lines(code, op_name)) > 0


def _scan_backwards_for_loop(lines: list[str], start: int, max_dist: int) -> int | None:
    """Scan backwards from start to find an enclosing loop."""
    if start >= len(lines) or start <= 0:
        return None
    target_indent = len(lines[start]) - len(lines[start].lstrip())
    # range must include 0
    for i in range(start - 1, max(-1, start - max_dist - 1), -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent < target_indent and any(kw in stripped for kw in ["for ", "while ", "range(", "retry", "attempt"]):
            return i
    return None


def _scan_for_guard(lines: list[str], start: int, end: int) -> bool:
    """Check for an idempotency guard between start and end lines."""
    for i in range(start, end):
        line = lines[i].strip()
        if line.startswith("if ") and any(g in line for g in [
            "not ", "already", "exists", "in seen", "in processed",
            "idempotency", "not in ", "_done", "_applied",
        ]):
            return True
    return False


def _extract_operation_pair(condition: str) -> tuple[str, str] | None:
    """Parse 'X_fails_after_Y' → ('Y', 'X')."""
    if "_fails_after_" in condition:
        parts = condition.split("_fails_after_")
        return parts[1].strip(), parts[0].strip()
    if "_after_" in condition:
        parts = condition.split("_after_")
        return parts[1].strip(), parts[0].strip()
    return None


def _extract_op_name(description: str) -> str:
    """Extract a function/operation name from a description string.

    Tries to match against known alias keys, then checks semantic synonyms,
    then falls back to word extraction.
    """
    desc_lower = description.lower()
    # Check if any alias key appears in the description
    for alias_key in OPERATION_ALIASES:
        if alias_key in desc_lower:
            return alias_key

    # Semantic synonyms — map common description words to alias keys
    _SYNONYMS = {
        "balance": "debit", "decrement": "debit", "subtract": "debit", "charge": "debit",
        "increment": "credit", "add": "credit", "refund": "credit",
        "write": "write_cache", "cache": "write_cache",
        "save": "commit", "persist": "commit", "flush": "commit",
        "reserve": "insert", "append": "insert",
    }
    for word in desc_lower.replace("_", " ").split():
        if word in _SYNONYMS:
            return _SYNONYMS[word]

    # Fallback: first substantial word
    for word in description.replace("_", " ").split():
        if len(word) > 2 and word.isalpha():
            return word
    return description.split()[0] if description.split() else ""


def _find_enclosing_try(lines: list[str], start: int, end: int) -> int | None:
    """Find a try: block near the vulnerable window (before or between start and end)."""
    # Look backwards from start
    for i in range(start, -1, -1):
        if "try:" in lines[i]:
            return i
    # Look between start and end (try may wrap the second operation)
    for i in range(start, min(end + 1, len(lines))):
        if "try:" in lines[i]:
            return i
    return None


def _extract_except_body(lines: list[str], try_line: int) -> str:
    """Extract the except block body after a try line."""
    body = []
    in_except = False
    for i in range(try_line + 1, min(len(lines), try_line + 30)):
        stripped = lines[i].strip()
        if stripped.startswith("except"):
            in_except = True
            continue
        if in_except:
            if stripped and not stripped.startswith(("try:", "finally:", "else:")):
                indent = len(lines[i]) - len(lines[i].lstrip())
                except_indent = len(lines[i-1]) - len(lines[i-1].lstrip()) if i > 0 else 0
                if indent <= except_indent and stripped:
                    break
                body.append(stripped)
            elif not stripped:
                body.append("")
    return "\n".join(body)
