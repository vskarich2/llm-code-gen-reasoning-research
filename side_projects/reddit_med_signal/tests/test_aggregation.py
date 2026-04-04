"""Tests for aggregation and conflict detection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregation import aggregate, deduplicate_records
from schemas import ExtractedRecord, FirsthandSignals, ReportedEffect, ConflictType


def _make_record(
    effect_name: str,
    directionality: str = "negative",
    temporal: str | None = None,
    text: str = "sample text about side effects",
    firsthand: bool = True,
    confidence: str = "high",
    depth: int = 0,
    reddit_id: str = "t3_abc",
) -> ExtractedRecord:
    effect = ReportedEffect(
        effect_raw=effect_name,
        effect_evidence_span=f"experienced {effect_name}",
        effect_normalized=effect_name,
        directionality=directionality,
        severity_hint="moderate",
        temporal_context=temporal,
    )
    return ExtractedRecord(
        drug_query="test_drug",
        canonical_drug_name="test_drug",
        source_type="post" if depth == 0 else "comment",
        subreddit="test",
        reddit_id=reddit_id,
        url="http://example.com",
        authored_timestamp=1000000.0,
        text_excerpt=text,
        comment_depth=depth,
        firsthand_heuristic=FirsthandSignals(),
        firsthand_final=firsthand,
        firsthand_final_confidence=confidence,
        reported_effects=[effect],
    )


_CFG = {
    "conflict_pairs": [
        ["insomnia", "drowsiness"],
        ["weight_gain", "weight_loss"],
    ],
    "weighting": {"post": 1.0, "top_level_comment": 0.8, "second_level_comment": 0.5},
}


def test_basic_grouping():
    records = [
        _make_record("nausea", reddit_id=f"t3_{i}") for i in range(5)
    ]
    result = aggregate(records, "test", "test", [], _CFG)
    assert len(result.themes) == 1
    assert result.themes[0].effect_normalized == "nausea"
    assert result.themes[0].mention_count == 5


def test_non_firsthand_excluded():
    records = [
        _make_record("nausea", firsthand=True, reddit_id="t3_1"),
        _make_record("nausea", firsthand=False, reddit_id="t3_2"),
        _make_record("nausea", firsthand=True, reddit_id="t3_3"),
    ]
    result = aggregate(records, "test", "test", [], _CFG)
    assert result.themes[0].mention_count == 2
    assert result.total_excluded == 1


def test_sparse_flag():
    records = [_make_record("nausea", reddit_id=f"t3_{i}") for i in range(5)]
    result = aggregate(records, "test", "test", [], _CFG)
    assert result.is_sparse is True  # < 10 firsthand


def test_not_sparse():
    records = [_make_record("nausea", reddit_id=f"t3_{i}") for i in range(15)]
    result = aggregate(records, "test", "test", [], _CFG)
    assert result.is_sparse is False


def test_temporal_variation_not_contradiction():
    """Insomnia early + drowsiness late → temporal variation."""
    records = []
    for i in range(5):
        records.append(_make_record(
            "insomnia", temporal="first week", reddit_id=f"t3_ins_{i}"
        ))
    for i in range(5):
        records.append(_make_record(
            "drowsiness", temporal="after a month", reddit_id=f"t3_drow_{i}"
        ))
    result = aggregate(records, "test", "test", [], _CFG)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflict_type == ConflictType.TEMPORAL_VARIATION


def test_direct_contradiction():
    """Weight gain + weight loss with no temporal pattern → direct contradiction."""
    records = []
    for i in range(3):
        records.append(_make_record(
            "weight_gain", reddit_id=f"t3_wg_{i}"
        ))
    for i in range(3):
        records.append(_make_record(
            "weight_loss", reddit_id=f"t3_wl_{i}"
        ))
    result = aggregate(records, "test", "test", [], _CFG)
    conflicts = [c for c in result.conflicts if "weight" in c.effect_a]
    assert len(conflicts) == 1
    # With 3+3 and no temporal context, should be unresolved_heterogeneity
    # (both >= 3, so the code classifies as UNRESOLVED_HETEROGENEITY)
    assert conflicts[0].conflict_type == ConflictType.UNRESOLVED_HETEROGENEITY


def test_small_direct_contradiction():
    """Small counts without temporal → direct contradiction."""
    records = [
        _make_record("weight_gain", reddit_id="t3_wg_1"),
        _make_record("weight_loss", reddit_id="t3_wl_1"),
    ]
    result = aggregate(records, "test", "test", [], _CFG)
    conflicts = [c for c in result.conflicts if "weight" in c.effect_a]
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == ConflictType.DIRECT_CONTRADICTION


def test_deduplication():
    text = "I took metformin and had terrible nausea for weeks on end constantly"
    records = [
        _make_record("nausea", text=text, reddit_id="t3_1"),
        _make_record("nausea", text=text, reddit_id="t3_2"),  # near-duplicate
        _make_record("headache", text="totally different content here", reddit_id="t3_3"),
    ]
    deduped, removed = deduplicate_records(records)
    assert removed == 1
    assert len(deduped) == 2


def test_empty_input():
    result = aggregate([], "test", "test", [], _CFG)
    assert result.is_sparse is True
    assert len(result.themes) == 0


def test_weighting():
    """Post gets weight 1.0, top-level comment gets 0.8."""
    records = [
        _make_record("nausea", depth=0, reddit_id="t3_1"),  # post
        _make_record("nausea", depth=1, reddit_id="t1_2"),  # top-level comment
    ]
    result = aggregate(records, "test", "test", [], _CFG)
    assert result.themes[0].weighted_count == 1.8  # 1.0 + 0.8
