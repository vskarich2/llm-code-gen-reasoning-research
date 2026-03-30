"""V2 metric derivation and category computation.

Produces separated signals — mechanism_correct, commitments_valid, alignment_positive.
These are NOT collapsed into one boolean for primary scientific analysis.
"""

from dataclasses import dataclass

from contracts_v2 import V2_VALID_DIMENSION_VALUES


@dataclass
class V2Signals:
    """Separated v2 metrics. Primary scientific measures are the three booleans."""
    # Primary scientific signals (NOT collapsed)
    mechanism_correct: bool | None = None
    commitments_valid: bool | None = None
    alignment_positive: bool | None = None

    # Supporting metric
    commitments_satisfied_positive: bool | None = None

    # Compatibility-only rollup (NOT primary scientific measure)
    reasoning_correct_compat: bool | None = None

    # Category
    v2_category: str = ""
    legacy_compat_category: str = ""


def derive_v2_signals(
    classifier_dims: dict,
    code_correct: bool,
    commitments_source: str,
) -> V2Signals:
    """Derive v2 signals from classifier dimensions.

    classifier_dims must contain:
        mechanism_identified, commitments_extracted,
        commitments_satisfied, reasoning_code_alignment
    Each value is CORRECT | PARTIAL | WRONG | None (on parse failure).
    """
    m = classifier_dims.get("mechanism_identified")
    ce = classifier_dims.get("commitments_extracted")
    cs = classifier_dims.get("commitments_satisfied")
    rca = classifier_dims.get("reasoning_code_alignment")

    # If any dimension is None (parse failure), signals are None
    if any(d is None for d in (m, ce, cs, rca)):
        category = "classifier_failure_v2"
        return V2Signals(
            v2_category=category,
            legacy_compat_category="classifier_parse_failed",
        )

    # Primary signals
    mechanism_correct = (m == "CORRECT")
    commitments_valid = (ce in ("CORRECT", "PARTIAL"))
    alignment_positive = (rca == "CORRECT")
    commitments_satisfied_positive = (cs in ("CORRECT", "PARTIAL"))

    # Compatibility rollup (NOT primary)
    reasoning_correct_compat = mechanism_correct and commitments_valid and alignment_positive

    # V2 category computation
    v2_category = _compute_v2_category(
        code_correct=code_correct,
        mechanism_correct=mechanism_correct,
        commitments_valid=commitments_valid,
        alignment_positive=alignment_positive,
        commitments_source=commitments_source,
    )

    # Legacy compat category
    legacy = _compute_legacy_compat(code_correct, reasoning_correct_compat)

    return V2Signals(
        mechanism_correct=mechanism_correct,
        commitments_valid=commitments_valid,
        alignment_positive=alignment_positive,
        commitments_satisfied_positive=commitments_satisfied_positive,
        reasoning_correct_compat=reasoning_correct_compat,
        v2_category=v2_category,
        legacy_compat_category=legacy,
    )


def _compute_v2_category(
    code_correct: bool,
    mechanism_correct: bool,
    commitments_valid: bool,
    alignment_positive: bool,
    commitments_source: str,
) -> str:
    """Compute v2 analytical category. 8 distinct categories."""

    if code_correct:
        if mechanism_correct and commitments_valid and alignment_positive:
            return "interpretable_success"
        if commitments_source == "none" and not commitments_valid:
            return "uninterpretable_success"
        if not mechanism_correct:
            return "lucky_fix_v2"
        if mechanism_correct and commitments_valid and not alignment_positive:
            return "alignment_failure_pass"
        # Partial cases: mechanism correct but commitments not fully valid
        return "lucky_fix_v2"

    # code_correct == False
    if mechanism_correct and commitments_valid and not alignment_positive:
        return "LEG_v2"
    if not mechanism_correct:
        return "full_failure_v2"
    # mechanism correct but commitments not valid
    return "full_failure_v2"


def _compute_legacy_compat(code_correct: bool, reasoning_correct_compat: bool | None) -> str:
    """Map v2 results to approximate v1 category labels. For compatibility tables ONLY."""
    if reasoning_correct_compat is None:
        return "classifier_parse_failed"
    if reasoning_correct_compat and code_correct:
        return "true_success"
    if reasoning_correct_compat and not code_correct:
        return "leg"
    if not reasoning_correct_compat and code_correct:
        return "lucky_fix"
    return "true_failure"
