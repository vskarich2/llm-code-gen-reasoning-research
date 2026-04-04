"""Reasoning/execution join. Derives signals internally.

No scoring. No thresholds. No categories beyond alignment.
"""

from core.evaluation import derive_v2_signals


def join_reasoning_execution(parsed_gen, classifier_result, exec_result,
                             case, condition, model):
    """Construct reasoning/execution relationship.

    Args:
        parsed_gen: ParsedGenerationV2 from parser.
        classifier_result: ClassifierResultV2 from evaluator.
        exec_result: dict from exec_canonical(). Must contain
            execution_category.
        case: case dict from cases_v2.json.
        condition: str condition name.
        model: str model name.

    Returns:
        dict with 7 fields: execution_pass, execution_category,
        mechanism_correct, commitments_valid, alignment_positive,
        reasoning_execution_alignment, signals.
    """
    if "execution_category" not in exec_result:
        raise RuntimeError("exec_result missing execution_category")
    category = exec_result["execution_category"]

    signals = derive_v2_signals(
        classifier_dims={
            "mechanism_identified":
                classifier_result.mechanism_identified,
            "commitments_extracted":
                classifier_result.commitments_extracted,
            "commitments_satisfied":
                classifier_result.commitments_satisfied,
            "reasoning_code_alignment":
                classifier_result.reasoning_code_alignment,
        },
        code_correct=exec_result.get("pass", False),
        commitments_source=(
            getattr(parsed_gen, "commitments_source", "none")
            if hasattr(parsed_gen, "commitments_source")
            else "none"),
    )

    exec_pass = exec_result.get("pass", False)
    mechanism_correct = signals.mechanism_correct
    commitments_valid = signals.commitments_valid
    alignment_positive = signals.alignment_positive

    if mechanism_correct is None:
        alignment = "unknown"
    elif mechanism_correct and exec_pass:
        alignment = "aligned"
    elif mechanism_correct and not exec_pass:
        alignment = "misaligned"
    elif not mechanism_correct and exec_pass:
        alignment = "lucky"
    else:
        alignment = "both_wrong"

    return {
        "execution_pass": exec_pass,
        "execution_category": category,
        "mechanism_correct": mechanism_correct,
        "commitments_valid": commitments_valid,
        "alignment_positive": alignment_positive,
        "reasoning_execution_alignment": alignment,
        "signals": signals,
    }
