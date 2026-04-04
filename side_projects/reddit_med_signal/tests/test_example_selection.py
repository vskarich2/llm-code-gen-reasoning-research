"""Tests for deterministic example selection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from example_selection import score_excerpt, select_top_excerpts
from schemas import ExtractedRecord, FirsthandSignals, ReportedEffect


def _make_record(
    confidence: str = "high",
    span: str = "I had moderate nausea for the first two weeks",
    temporal: str | None = "first two weeks",
    extraction_conf: str = "high",
    flags: list[str] | None = None,
    timestamp: float = 1000.0,
    url: str = "http://example.com",
) -> ExtractedRecord:
    effect = ReportedEffect(
        effect_raw="nausea",
        effect_evidence_span=span,
        effect_normalized="nausea",
        directionality="negative",
        severity_hint="moderate",
        temporal_context=temporal,
        extraction_confidence=extraction_conf,
    )
    return ExtractedRecord(
        drug_query="test",
        canonical_drug_name="test",
        source_type="post",
        subreddit="test",
        reddit_id="t3_abc",
        url=url,
        authored_timestamp=timestamp,
        text_excerpt="full text",
        firsthand_heuristic=FirsthandSignals(),
        firsthand_final=True,
        firsthand_final_confidence=confidence,
        reported_effects=[effect],
        uncertainty_flags=flags or [],
    )


def test_high_confidence_preferred():
    high = _make_record(confidence="high")
    low = _make_record(confidence="low")
    s_high = score_excerpt(high, high.reported_effects[0])
    s_low = score_excerpt(low, low.reported_effects[0])
    assert s_high > s_low


def test_good_length_preferred():
    good = _make_record(span="I experienced moderate nausea and stomach cramping every morning")
    short = _make_record(span="nausea")
    s_good = score_excerpt(good, good.reported_effects[0])
    s_short = score_excerpt(short, short.reported_effects[0])
    assert s_good > s_short


def test_temporal_context_bonus():
    with_temporal = _make_record(temporal="first two weeks")
    without = _make_record(temporal=None)
    s_with = score_excerpt(with_temporal, with_temporal.reported_effects[0])
    s_without = score_excerpt(without, without.reported_effects[0])
    assert s_with > s_without


def test_low_uncertainty_preferred():
    clean = _make_record(flags=[])
    uncertain = _make_record(flags=["speculative", "unclear_causation"])
    s_clean = score_excerpt(clean, clean.reported_effects[0])
    s_uncertain = score_excerpt(uncertain, uncertain.reported_effects[0])
    assert s_clean > s_uncertain


def test_top_3_selected():
    records = [
        _make_record(
            confidence="high",
            span=f"nausea experience number {i} was quite notable and distinct",
            timestamp=float(1000 + i),
            url=f"http://example.com/{i}",
        )
        for i in range(10)
    ]
    results = select_top_excerpts(records, "nausea", n=3)
    assert len(results) == 3


def test_tie_broken_by_recency():
    old = _make_record(timestamp=1000.0, url="http://old.com")
    new = _make_record(timestamp=2000.0, url="http://new.com")
    results = select_top_excerpts([old, new], "nausea", n=1)
    assert len(results) == 1
    assert results[0][1] == "http://new.com"
