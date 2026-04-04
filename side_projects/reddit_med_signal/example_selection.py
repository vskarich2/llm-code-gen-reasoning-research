"""Deterministic excerpt scoring and ranking for report examples."""

from __future__ import annotations

from schemas import ExtractedRecord, ReportedEffect


def score_excerpt(record: ExtractedRecord, effect: ReportedEffect) -> float:
    """Score a single excerpt for use as an example in the report.

    Higher is better. Max possible score: 8.0.
    """
    score = 0.0

    # 1. Firsthand confidence (0-3 points)
    confidence_map = {"high": 3.0, "medium": 1.5, "low": 0.5}
    score += confidence_map.get(record.firsthand_final_confidence, 0.0)

    # 2. Evidence span specificity (0-2 points)
    span_len = len(effect.effect_evidence_span)
    if 40 <= span_len <= 300:
        score += 2.0
    elif 20 <= span_len < 40:
        score += 1.0
    elif span_len > 300:
        score += 0.5
    # Very short spans (<20) get 0

    # 3. Temporal context present (0-1 point)
    if effect.temporal_context:
        score += 1.0

    # 4. Extraction confidence (0-1 point)
    if effect.extraction_confidence == "high":
        score += 1.0
    elif effect.extraction_confidence == "medium":
        score += 0.5

    # 5. Low uncertainty (0-1 point)
    if not record.uncertainty_flags:
        score += 1.0
    elif len(record.uncertainty_flags) == 1:
        score += 0.5

    return score


def select_top_excerpts(
    records: list[ExtractedRecord],
    effect_normalized: str,
    n: int = 3,
) -> list[tuple[str, str, float]]:
    """Select top N excerpts for a given normalized effect.

    Returns list of (evidence_span, url, score) tuples, sorted by score desc.
    Ties broken by authored_timestamp desc (prefer recent).
    """
    candidates: list[tuple[str, str, float, float]] = []

    for record in records:
        if not record.firsthand_final:
            continue
        for effect in record.reported_effects:
            if effect.effect_normalized != effect_normalized:
                continue
            s = score_excerpt(record, effect)
            candidates.append((
                effect.effect_evidence_span,
                record.url,
                s,
                record.authored_timestamp,
            ))

    # Sort by score desc, then timestamp desc
    candidates.sort(key=lambda x: (x[2], x[3]), reverse=True)

    return [(span, url, score) for span, url, score, _ in candidates[:n]]
