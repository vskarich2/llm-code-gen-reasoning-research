"""Final ev dict assembly. LEG detection. Lucky fix detection.

Requires exec_result (not None) because assemble_v2_result uses it
for pass/fail, score, execution metadata.
"""

from core.evaluation.evaluator_v2 import assemble_v2_result


def score_execution(joined, artifact, classifier_result, exec_result,
                    case, condition, model):
    """Build final ev dict.

    Args:
        joined: dict from join_reasoning_execution(). Must contain
            all 7 fields.
        artifact: NormalizedReasoningArtifactV2 from Stage B.
        classifier_result: ClassifierResultV2 from evaluator.
        exec_result: dict from exec_canonical(). Must not be None.
        case: case dict.
        condition: str condition name.
        model: str model name.

    Returns:
        Full ev dict for logging.
    """
    signals = joined["signals"]

    ev = assemble_v2_result(
        exec_result=exec_result,
        artifact=artifact,
        classifier=classifier_result,
        signals=signals,
        case=case,
        condition=condition,
        model=model,
    )

    ev["execution_category"] = joined["execution_category"]
    ev["reasoning_execution_alignment"] = (
        joined["reasoning_execution_alignment"])
    # FIX-NOW-5: None reasoning_consistent means "not evaluated",
    # not "wrong". Do not conflate with False.
    mc = joined.get("reasoning_consistent") or joined.get("reasoning_consistent")
    if mc is None:
        ev["leg_candidate"] = None  # unknown
        ev["lucky_fix_candidate"] = None  # unknown
    else:
        ev["leg_candidate"] = (mc is True and not joined["execution_pass"])
        ev["lucky_fix_candidate"] = (
            joined["execution_pass"] and mc is False
        )

    return ev
