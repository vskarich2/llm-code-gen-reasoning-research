"""Disagreement classifier for dual execution system.

Deterministic classification of WHY concat and module execution disagree.
Pure function — no external state, no randomness.

Classification priority (strict order):
  1. TEST_INCONSISTENCY
  2. AGREEMENT
  3. ASSEMBLY_FAILURE_LIKELY
  4. MODULE_EXECUTION_FAILURE
  5. SEMANTIC_DIVERGENCE
  6. CONSISTENT_FAILURE
  7. UNKNOWN

Confidence scores are ORDINAL RULE-STRENGTH, not calibrated probabilities.
  1.0 = exact rule match
  0.8 = strong signal match
  0.5 = weak heuristic match
  0.0 = unknown
They MUST NOT be used in probabilistic models or Bayesian updates.
Validated empirically via manual audit.
"""

import re
from dataclasses import dataclass, field


# ============================================================
# RESULT SCHEMA
# ============================================================


@dataclass
class DisagreementResult:
    type: str
    subtype: str | None = None
    confidence: float = 0.0
    evidence: dict = field(default_factory=dict)
    assembly_confirmed: bool = False


# ============================================================
# SIGNAL EXTRACTION
# ============================================================

_IMPORT_KEYWORDS = frozenset({
    "modulenotfounderror", "importerror", "no module named",
    "cannot import name", "import",
})

_NAME_KEYWORDS = frozenset({
    "nameerror", "is not defined", "name '",
})

_ATTR_KEYWORDS = frozenset({
    "attributeerror", "has no attribute", "module",
})

_CIRCULAR_KEYWORDS = frozenset({
    "circular", "partially initialized", "cannot import name",
    "most likely due to a circular import",
})


def _extract_keywords(text: str) -> set:
    if not text:
        return set()
    lower = text.lower()
    return {kw for kw in _IMPORT_KEYWORDS | _NAME_KEYWORDS | _ATTR_KEYWORDS | _CIRCULAR_KEYWORDS
            if kw in lower}


def _extract_error_type(error: str | None) -> str:
    if not error:
        return ""
    for prefix in ("ModuleNotFoundError", "ImportError", "NameError",
                    "AttributeError", "SyntaxError", "TypeError",
                    "ValueError", "RuntimeError", "RecursionError"):
        if prefix.lower() in error.lower():
            return prefix
    return "Other"


def _extract_missing_symbol(error: str | None) -> str | None:
    """Extract the symbol name from a NameError message."""
    if not error:
        return None
    try:
        m = re.search(r"name '(\w+)' is not defined", error)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_attr_object_name(error: str | None) -> str | None:
    """Extract the object name from an AttributeError message. Best-effort."""
    if not error:
        return None
    try:
        # Attempt 1: "'X' object has no attribute 'Y'"
        m = re.match(r"'(\w+)' object has no attribute '(\w+)'", error)
        if m:
            return m.group(1)
        # Attempt 2: "module 'X' has no attribute 'Y'"
        m = re.match(r"module '(\w+)' has no attribute", error)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_signals(concat_result: dict, module_result: dict) -> dict:
    c_error = concat_result.get("error") or ""
    m_error = module_result.get("error") or ""
    c_tb = concat_result.get("traceback") or ""
    m_tb = module_result.get("traceback") or ""
    c_text = f"{c_error} {c_tb}"
    m_text = f"{m_error} {m_tb}"

    return {
        "concat_pass": concat_result.get("pass", False),
        "module_pass": module_result.get("pass", False),
        "concat_error_type": _extract_error_type(c_error or c_tb),
        "module_error_type": _extract_error_type(m_error or m_tb),
        "concat_keywords": _extract_keywords(c_text),
        "module_keywords": _extract_keywords(m_text),
        "concat_tests_run": concat_result.get("tests_run", 0),
        "module_tests_run": module_result.get("tests_run", 0),
        "concat_tests_passed": concat_result.get("tests_passed", 0),
        "module_tests_passed": module_result.get("tests_passed", 0),
        "stdout_diff": concat_result.get("stdout", "") != module_result.get("stdout", ""),
        "tests_diff": concat_result.get("tests_run", 0) != module_result.get("tests_run", 0),
        "concat_missing_symbol": _extract_missing_symbol(c_error or c_tb),
        "concat_attr_object": _extract_attr_object_name(c_error or c_tb),
    }


# ============================================================
# FORMAL assembly_confirmed COMPUTATION
# ============================================================


def compute_assembly_confirmed(
    disagreement: "DisagreementResult",
    concat_result: dict,
    module_result: dict,
    assembly_rewrites: list | None = None,
    qualified_imports_resolved: list | None = None,
    confidence_threshold: float = 0.8,
) -> bool:
    """Compute formal assembly_confirmed using explicit boolean signals.

    Requires:
      - disagreement is assembly_failure_likely with confidence >= threshold
      - at least one structural signal: has_import_error OR has_missing_symbol OR has_namespace_error

    assembly_rewrites: list of rewrite dicts from AssemblyResult.rewrites_applied
    qualified_imports_resolved: list from AssemblyResult.qualified_imports_resolved
    """
    # Gate: must be assembly_suspect
    if not (not concat_result.get("pass", True) and module_result.get("pass", False)):
        return False

    # Gate: classifier type and confidence
    if disagreement.type != "assembly_failure_likely":
        return False
    if disagreement.confidence < confidence_threshold:
        return False

    c_error = concat_result.get("error") or ""
    c_tb = concat_result.get("traceback") or ""
    c_text = f"{c_error} {c_tb}"

    # Signal 1: Import-class error (typed check, not keyword)
    c_err_type = _extract_error_type(c_text)
    has_import_error = c_err_type in ("ModuleNotFoundError", "ImportError")

    # Signal 2: Missing symbol that was stripped/rewritten
    has_missing_symbol = False
    missing_sym = _extract_missing_symbol(c_text)
    if missing_sym and assembly_rewrites:
        expected_symbols = set()
        for r in assembly_rewrites:
            rtype = r.get("type", "")
            if rtype == "alias_rename":
                expected_symbols.add(r.get("alias", ""))
            elif rtype == "remove_from_import":
                expected_symbols.update(r.get("names", []))
            elif rtype == "remove_bare_import":
                expected_symbols.add(r.get("module", ""))
            elif rtype == "qualified_import_resolved":
                expected_symbols.add(r.get("effective_name", ""))
        has_missing_symbol = missing_sym in expected_symbols

    # Signal 3: Attribute error on synthesized namespace
    has_namespace_error = False
    if qualified_imports_resolved:
        obj_name = _extract_attr_object_name(c_text)
        if obj_name:
            synth_names = {r.get("effective_name", "") for r in qualified_imports_resolved}
            has_namespace_error = c_err_type == "AttributeError" and obj_name in synth_names

    return has_import_error or has_missing_symbol or has_namespace_error


# ============================================================
# CLASSIFICATION (strict priority order)
# ============================================================


def classify_disagreement(concat_result: dict, module_result: dict) -> DisagreementResult:
    """Classify the disagreement between concat and module execution.

    Pure function. Deterministic. Exactly one primary type.
    """
    signals = _extract_signals(concat_result, module_result)
    c_pass = signals["concat_pass"]
    m_pass = signals["module_pass"]

    # ── 1. TEST_INCONSISTENCY ──
    if signals["tests_diff"]:
        c_run = signals["concat_tests_run"]
        m_run = signals["module_tests_run"]
        if c_run == 0 or m_run == 0:
            subtype = "early_failure"
        elif c_run > m_run:
            subtype = "partial_execution"
        else:
            subtype = "test_harness_mismatch"
        return DisagreementResult(
            type="test_inconsistency", subtype=subtype, confidence=1.0,
            evidence={"concat_tests_run": c_run, "module_tests_run": m_run},
        )

    # ── 2. AGREEMENT ──
    if c_pass == m_pass and signals["concat_tests_passed"] == signals["module_tests_passed"]:
        return DisagreementResult(
            type="agreement", confidence=1.0,
            evidence={"pass": c_pass, "tests_passed": signals["concat_tests_passed"]},
        )

    # ── 3. ASSEMBLY_FAILURE_LIKELY (concat fails, module passes) ──
    if not c_pass and m_pass:
        c_kw = signals["concat_keywords"]
        c_err = signals["concat_error_type"]

        if c_kw & _IMPORT_KEYWORDS:
            return DisagreementResult(
                type="assembly_failure_likely", subtype="import_resolution_failure",
                confidence=1.0,
                evidence={"concat_error_type": c_err, "keywords": sorted(c_kw & _IMPORT_KEYWORDS),
                          "missing_symbol": signals["concat_missing_symbol"]},
            )

        if c_err == "NameError" or c_kw & _NAME_KEYWORDS:
            return DisagreementResult(
                type="assembly_failure_likely", subtype="missing_symbol_after_strip",
                confidence=0.8,
                evidence={"concat_error_type": c_err, "missing_symbol": signals["concat_missing_symbol"],
                          "keywords": sorted(c_kw & _NAME_KEYWORDS)},
            )

        if c_err == "AttributeError" or c_kw & _ATTR_KEYWORDS:
            return DisagreementResult(
                type="assembly_failure_likely", subtype="namespace_binding_failure",
                confidence=0.8,
                evidence={"concat_error_type": c_err, "attr_object": signals["concat_attr_object"],
                          "keywords": sorted(c_kw & _ATTR_KEYWORDS)},
            )

        return DisagreementResult(
            type="assembly_failure_likely", subtype="unclassified_concat_failure",
            confidence=0.5,
            evidence={"concat_error_type": c_err, "concat_keywords": sorted(c_kw)},
        )

    # ── 4. MODULE_EXECUTION_FAILURE (concat passes, module fails) ──
    if c_pass and not m_pass:
        m_kw = signals["module_keywords"]
        m_err = signals["module_error_type"]

        if m_kw & _CIRCULAR_KEYWORDS:
            return DisagreementResult(
                type="module_execution_failure", subtype="circular_import_failure",
                confidence=1.0,
                evidence={"module_error_type": m_err, "keywords": sorted(m_kw & _CIRCULAR_KEYWORDS)},
            )

        if m_kw & _IMPORT_KEYWORDS:
            return DisagreementResult(
                type="module_execution_failure", subtype="module_init_order_failure",
                confidence=0.8,
                evidence={"module_error_type": m_err, "keywords": sorted(m_kw & _IMPORT_KEYWORDS)},
            )

        return DisagreementResult(
            type="module_execution_failure", subtype="unclassified_module_failure",
            confidence=0.5,
            evidence={"module_error_type": m_err, "module_keywords": sorted(m_kw)},
        )

    # ── 5. SEMANTIC_DIVERGENCE (both pass but different results) ──
    if c_pass and m_pass:
        if signals["stdout_diff"]:
            return DisagreementResult(
                type="semantic_divergence", subtype="state_order_difference",
                confidence=0.8, evidence={"stdout_diff": True},
            )
        return DisagreementResult(
            type="semantic_divergence", subtype="test_result_difference",
            confidence=0.8,
            evidence={"concat_tests_passed": signals["concat_tests_passed"],
                      "module_tests_passed": signals["module_tests_passed"]},
        )

    # ── 6. CONSISTENT_FAILURE (both fail) ──
    if not c_pass and not m_pass:
        c_err = signals["concat_error_type"]
        m_err = signals["module_error_type"]
        if c_err == m_err:
            return DisagreementResult(
                type="consistent_failure", subtype="same_error",
                confidence=1.0, evidence={"error_type": c_err},
            )
        return DisagreementResult(
            type="consistent_failure", subtype="different_error",
            confidence=0.8,
            evidence={"concat_error_type": c_err, "module_error_type": m_err},
        )

    # ── 7. UNKNOWN ──
    return DisagreementResult(
        type="unknown", confidence=0.0,
        evidence={"concat_result_pass": c_pass, "module_result_pass": m_pass, "signals": signals},
    )
