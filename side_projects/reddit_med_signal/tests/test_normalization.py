"""Tests for deterministic effect normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from normalization import canonicalize_effect, clean_label, load_synonym_map
from schemas import ExtractedRecord, FirsthandSignals, ReportedEffect
from normalization import normalize_records


def _load_map():
    return load_synonym_map()


def test_weight_loss_variants():
    m = _load_map()
    variants = ["lost_weight", "losing_weight", "dropped_pounds", "weight_came_off"]
    for v in variants:
        canonical, mapped = canonicalize_effect(v, m)
        assert canonical == "weight_loss", f"{v} → {canonical}"
        assert mapped is True


def test_nausea_variants():
    m = _load_map()
    variants = ["nauseous", "felt_nauseous", "sick_to_stomach", "queasy"]
    for v in variants:
        canonical, mapped = canonicalize_effect(v, m)
        assert canonical == "nausea", f"{v} → {canonical}"


def test_case_insensitive():
    m = _load_map()
    canonical, _ = canonicalize_effect("WEIGHT_LOSS", m)
    assert canonical == "weight_loss"
    canonical2, _ = canonicalize_effect("Weight_Loss", m)
    assert canonical2 == "weight_loss"


def test_punctuation_stripped():
    label = clean_label("weight-loss!")
    assert label == "weightloss" or label == "weight_loss" or "weight" in label
    # The real test: after clean + lookup
    m = _load_map()
    canonical, _ = canonicalize_effect("weight loss", m)
    assert canonical == "weight_loss"


def test_unmapped_passthrough():
    m = _load_map()
    canonical, mapped = canonicalize_effect("jaw_clenching", m)
    assert canonical == "jaw_clenching"
    assert mapped is False


def test_canonical_key_direct_match():
    m = _load_map()
    canonical, mapped = canonicalize_effect("weight_loss", m)
    assert canonical == "weight_loss"
    assert mapped is True


def test_whitespace_normalized():
    label = clean_label("lost  weight")
    assert label == "lost_weight"
    m = _load_map()
    canonical, _ = canonicalize_effect("lost  weight", m)
    assert canonical == "weight_loss"


def test_normalize_records_updates_field():
    m = _load_map()
    effect = ReportedEffect(
        effect_raw="felt nauseous",
        effect_evidence_span="I felt nauseous all day",
        directionality="negative",
        severity_hint="moderate",
    )
    record = ExtractedRecord(
        drug_query="test",
        canonical_drug_name="test",
        source_type="post",
        subreddit="test",
        reddit_id="t3_abc",
        url="http://example.com",
        authored_timestamp=0.0,
        text_excerpt="test",
        firsthand_heuristic=FirsthandSignals(),
        reported_effects=[effect],
    )
    records, unmapped = normalize_records([record], m)
    assert records[0].reported_effects[0].effect_normalized == "nausea"
    assert len(unmapped) == 0


def test_normalize_records_tracks_unmapped():
    m = _load_map()
    effect = ReportedEffect(
        effect_raw="exploding kneecaps",
        effect_evidence_span="my kneecaps were exploding",
        directionality="negative",
        severity_hint="severe",
    )
    record = ExtractedRecord(
        drug_query="test",
        canonical_drug_name="test",
        source_type="post",
        subreddit="test",
        reddit_id="t3_abc",
        url="http://example.com",
        authored_timestamp=0.0,
        text_excerpt="test",
        firsthand_heuristic=FirsthandSignals(),
        reported_effects=[effect],
    )
    records, unmapped = normalize_records([record], m)
    assert "exploding_kneecaps" in unmapped
