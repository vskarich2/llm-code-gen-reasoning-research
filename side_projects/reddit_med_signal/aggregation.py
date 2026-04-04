"""Deterministic aggregation with nuanced conflict taxonomy. No LLM calls."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from example_selection import select_top_excerpts
from schemas import (
    AggregationResult,
    ConflictRecord,
    ConflictType,
    EffectTheme,
    ExtractedRecord,
)

_log = logging.getLogger("reddit_med_signal.aggregation")

# Temporal markers for conflict classification
_EARLY_MARKERS = {
    "first week", "first month", "initially", "starting", "early",
    "beginning", "day 1", "week 1", "week 2", "first few days",
    "first few weeks", "first 2 weeks", "right away", "immediately",
}
_LATE_MARKERS = {
    "eventually", "after a month", "months later", "long-term",
    "over time", "settled", "wore off", "after several weeks",
    "after a few months", "long term", "weeks later",
}

_DOSE_PATTERN = re.compile(r"\b\d+\s*mg\b", re.IGNORECASE)


def _get_weight(record: ExtractedRecord, cfg: dict) -> float:
    """Get the weight for a record based on source type and depth."""
    weights = cfg.get("weighting", {})
    if record.source_type == "post":
        return weights.get("post", 1.0)
    if record.comment_depth <= 1:
        return weights.get("top_level_comment", 0.8)
    return weights.get("second_level_comment", 0.5)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts (word-level)."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def deduplicate_records(
    records: list[ExtractedRecord],
    similarity_threshold: float = 0.85,
) -> tuple[list[ExtractedRecord], int]:
    """Remove near-duplicate records based on text similarity.

    Returns (deduped_records, num_removed).
    """
    if not records:
        return records, 0

    kept: list[ExtractedRecord] = []
    removed = 0

    for record in records:
        is_dup = False
        for existing in kept:
            sim = _jaccard_similarity(record.text_excerpt, existing.text_excerpt)
            if sim >= similarity_threshold:
                is_dup = True
                break
        if is_dup:
            removed += 1
        else:
            kept.append(record)

    if removed > 0:
        _log.info("Deduplication: removed %d near-duplicate records", removed)
    return kept, removed


def _classify_temporal(
    records_a: list[ExtractedRecord],
    records_b: list[ExtractedRecord],
    effect_a: str,
    effect_b: str,
) -> bool:
    """Check if the conflict is likely a temporal variation."""
    a_temporals: list[str] = []
    for r in records_a:
        for e in r.reported_effects:
            if e.effect_normalized == effect_a and e.temporal_context:
                a_temporals.append(e.temporal_context.lower())

    b_temporals: list[str] = []
    for r in records_b:
        for e in r.reported_effects:
            if e.effect_normalized == effect_b and e.temporal_context:
                b_temporals.append(e.temporal_context.lower())

    if not a_temporals or not b_temporals:
        return False

    a_early = sum(
        1 for t in a_temporals if any(m in t for m in _EARLY_MARKERS)
    )
    b_late = sum(
        1 for t in b_temporals if any(m in t for m in _LATE_MARKERS)
    )
    # Also check the reverse
    b_early = sum(
        1 for t in b_temporals if any(m in t for m in _EARLY_MARKERS)
    )
    a_late = sum(
        1 for t in a_temporals if any(m in t for m in _LATE_MARKERS)
    )

    # At least 40% of one side clusters early, 40% of other clusters late
    min_a = max(len(a_temporals), 1)
    min_b = max(len(b_temporals), 1)

    pattern1 = (a_early / min_a) > 0.4 and (b_late / min_b) > 0.4
    pattern2 = (b_early / min_b) > 0.4 and (a_late / min_a) > 0.4
    return pattern1 or pattern2


def _classify_dose_context(
    records_a: list[ExtractedRecord],
    records_b: list[ExtractedRecord],
) -> bool:
    """Check if the conflict is likely dose/context related."""
    a_doses: set[str] = set()
    for r in records_a:
        matches = _DOSE_PATTERN.findall(r.text_excerpt)
        a_doses.update(m.lower() for m in matches)

    b_doses: set[str] = set()
    for r in records_b:
        matches = _DOSE_PATTERN.findall(r.text_excerpt)
        b_doses.update(m.lower() for m in matches)

    # If both sides mention doses and the dose sets are disjoint, likely dose-related
    if a_doses and b_doses and not a_doses.intersection(b_doses):
        return True
    return False


def _detect_conflicts(
    effect_to_records: dict[str, list[ExtractedRecord]],
    conflict_pairs: list[list[str]],
    all_records: list[ExtractedRecord],
) -> list[ConflictRecord]:
    """Detect and classify conflicts between opposing effect pairs."""
    conflicts: list[ConflictRecord] = []

    for pair in conflict_pairs:
        if len(pair) != 2:
            continue
        eff_a, eff_b = pair[0], pair[1]
        recs_a = effect_to_records.get(eff_a, [])
        recs_b = effect_to_records.get(eff_b, [])

        if not recs_a or not recs_b:
            continue

        # Classify the conflict type
        if _classify_temporal(recs_a, recs_b, eff_a, eff_b):
            conflict_type = ConflictType.TEMPORAL_VARIATION
            summary = (
                f"'{eff_a}' and '{eff_b}' may reflect temporal variation — "
                f"one tends to appear early, the other later."
            )
        elif _classify_dose_context(recs_a, recs_b):
            conflict_type = ConflictType.DOSE_CONTEXT_VARIATION
            summary = (
                f"'{eff_a}' and '{eff_b}' may be dose-dependent — "
                f"different dosages mentioned in each group."
            )
        elif len(recs_a) >= 3 and len(recs_b) >= 3:
            conflict_type = ConflictType.UNRESOLVED_HETEROGENEITY
            summary = (
                f"Both '{eff_a}' ({len(recs_a)} mentions) and "
                f"'{eff_b}' ({len(recs_b)} mentions) are substantially "
                f"reported. Individual variation is likely."
            )
        else:
            conflict_type = ConflictType.DIRECT_CONTRADICTION
            summary = (
                f"'{eff_a}' ({len(recs_a)} mentions) and "
                f"'{eff_b}' ({len(recs_b)} mentions) directly conflict."
            )

        # Get example excerpts
        ex_a = ""
        for r in recs_a:
            for e in r.reported_effects:
                if e.effect_normalized == eff_a and e.effect_evidence_span:
                    ex_a = e.effect_evidence_span[:200]
                    break
            if ex_a:
                break

        ex_b = ""
        for r in recs_b:
            for e in r.reported_effects:
                if e.effect_normalized == eff_b and e.effect_evidence_span:
                    ex_b = e.effect_evidence_span[:200]
                    break
            if ex_b:
                break

        conflicts.append(ConflictRecord(
            effect_a=eff_a,
            effect_b=eff_b,
            conflict_type=conflict_type,
            evidence_summary=summary,
            count_a=len(recs_a),
            count_b=len(recs_b),
            example_a=ex_a,
            example_b=ex_b,
        ))

    return conflicts


def aggregate(
    records: list[ExtractedRecord],
    drug_query: str,
    canonical_name: str,
    unmapped_labels: list[str],
    cfg: dict,
    raw_count: int = 0,
    filtered_count: int = 0,
    extraction_attempted: int = 0,
    extraction_succeeded: int = 0,
    extraction_failed: int = 0,
    dedup_removed: int = 0,
    ungrounded_dropped: int = 0,
    run_timestamp: str = "",
) -> AggregationResult:
    """Aggregate extracted records into themes and conflicts."""
    conflict_pairs = cfg.get("conflict_pairs", [])

    # Separate firsthand from excluded
    firsthand_records: list[ExtractedRecord] = []
    excluded = 0
    high_count = 0
    med_count = 0
    low_count = 0

    for r in records:
        if r.firsthand_final:
            firsthand_records.append(r)
            if r.firsthand_final_confidence == "high":
                high_count += 1
            elif r.firsthand_final_confidence == "medium":
                med_count += 1
            else:
                low_count += 1
        else:
            excluded += 1

    is_sparse = len(firsthand_records) < 10

    # Group by normalized effect
    effect_to_records: dict[str, list[ExtractedRecord]] = defaultdict(list)
    effect_to_effects: dict[str, list[tuple[ExtractedRecord, "ReportedEffect"]]] = defaultdict(list)

    for record in firsthand_records:
        for effect in record.reported_effects:
            norm = effect.effect_normalized
            if norm:
                effect_to_records[norm].append(record)
                effect_to_effects[norm].append((record, effect))

    # Build themes
    themes: list[EffectTheme] = []
    for norm_label, rec_effect_pairs in effect_to_effects.items():
        dir_breakdown: dict[str, int] = defaultdict(int)
        sev_breakdown: dict[str, int] = defaultdict(int)
        chains: set[str] = set()
        weighted_total = 0.0

        for record, effect in rec_effect_pairs:
            dir_breakdown[effect.directionality] += 1
            sev_breakdown[effect.severity_hint] += 1
            weighted_total += _get_weight(record, cfg)
            if effect.is_secondorder and effect.secondorder_chain:
                chains.add(effect.secondorder_chain)

        # Select best examples
        top_excerpts = select_top_excerpts(
            firsthand_records, norm_label, n=3
        )

        theme = EffectTheme(
            effect_normalized=norm_label,
            mention_count=len(rec_effect_pairs),
            weighted_count=round(weighted_total, 2),
            directionality_breakdown=dict(dir_breakdown),
            severity_breakdown=dict(sev_breakdown),
            has_contradiction=False,
            secondorder_chains=sorted(chains),
            example_excerpts=[span for span, _, _ in top_excerpts],
            example_urls=[url for _, url, _ in top_excerpts],
            example_scores=[score for _, _, score in top_excerpts],
        )
        themes.append(theme)

    # Sort by mention count descending
    themes.sort(key=lambda t: t.mention_count, reverse=True)

    # Detect conflicts
    conflicts = _detect_conflicts(
        effect_to_records, conflict_pairs, firsthand_records
    )

    # Mark themes involved in conflicts
    conflict_effects = set()
    for c in conflicts:
        conflict_effects.add(c.effect_a)
        conflict_effects.add(c.effect_b)
    for theme in themes:
        if theme.effect_normalized in conflict_effects:
            theme.has_contradiction = True

    # Co-medication counts
    co_med_counts: dict[str, int] = defaultdict(int)
    for record in firsthand_records:
        for med in record.co_medications:
            co_med_counts[med.lower()] += 1

    # Uncertainty summary
    uncertainty: dict[str, int] = defaultdict(int)
    for record in firsthand_records:
        for flag in record.uncertainty_flags:
            # Strip the count suffix from ungrounded flags
            base_flag = flag.split(":")[0]
            uncertainty[base_flag] += 1

    # Count ungrounded effects
    for record in records:
        for flag in record.uncertainty_flags:
            if flag.startswith("ungrounded_effects_dropped:"):
                try:
                    ungrounded_dropped += int(flag.split(":")[1])
                except (ValueError, IndexError):
                    pass

    result = AggregationResult(
        drug_query=drug_query,
        canonical_drug_name=canonical_name,
        total_raw_items=raw_count,
        total_after_heuristic_filter=filtered_count,
        total_extraction_attempted=extraction_attempted,
        total_extraction_succeeded=extraction_succeeded,
        total_extraction_failed=extraction_failed,
        total_firsthand_high=high_count,
        total_firsthand_medium=med_count,
        total_firsthand_low=low_count,
        total_excluded=excluded,
        total_deduped=dedup_removed,
        ungrounded_effects_dropped=ungrounded_dropped,
        is_sparse=is_sparse,
        themes=themes,
        conflicts=conflicts,
        co_medication_counts=dict(co_med_counts),
        uncertainty_summary=dict(uncertainty),
        unmapped_labels=unmapped_labels,
        run_timestamp=run_timestamp,
        config_snapshot=cfg,
    )

    _log.info(
        "Aggregation: %d firsthand records → %d themes, %d conflicts, sparse=%s",
        len(firsthand_records), len(themes), len(conflicts), is_sparse,
    )
    return result
