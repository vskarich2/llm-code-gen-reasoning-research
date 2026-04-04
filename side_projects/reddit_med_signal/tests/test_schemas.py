"""Tests for Pydantic schema validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pydantic import ValidationError

from schemas import ExtractedRecord, FirsthandSignals, RawItem, ReportedEffect


def test_raw_item_roundtrip():
    item = RawItem(
        item_type="post",
        reddit_id="t3_abc123",
        subreddit="diabetes",
        url="http://example.com",
        author="test_user",
        created_utc=1711929600.0,
        score=42,
        title="Test post",
        body="Some body text here",
        comment_depth=0,
        retrieved_at="2026-04-01T00:00:00",
    )
    json_str = item.model_dump_json()
    restored = RawItem.model_validate_json(json_str)
    assert restored.reddit_id == "t3_abc123"
    assert restored.item_type == "post"
    assert restored.score == 42


def test_extracted_record_roundtrip():
    record = ExtractedRecord(
        drug_query="metformin",
        canonical_drug_name="metformin",
        source_type="comment",
        subreddit="diabetes",
        reddit_id="t1_xyz",
        url="http://example.com",
        authored_timestamp=1711929600.0,
        text_excerpt="I took metformin and felt nauseous",
        comment_depth=1,
        firsthand_heuristic=FirsthandSignals(
            has_first_person_pronoun=True,
            has_self_use_verb=True,
            heuristic_firsthand_score="strong_yes",
        ),
        firsthand_final=True,
        firsthand_final_confidence="high",
        reported_effects=[
            ReportedEffect(
                effect_raw="nausea",
                effect_evidence_span="felt nauseous",
                effect_normalized="nausea",
                directionality="negative",
                severity_hint="moderate",
            )
        ],
    )
    json_str = record.model_dump_json()
    restored = ExtractedRecord.model_validate_json(json_str)
    assert restored.firsthand_final is True
    assert len(restored.reported_effects) == 1
    assert restored.reported_effects[0].effect_normalized == "nausea"


def test_invalid_directionality():
    with pytest.raises(ValidationError):
        ReportedEffect(
            effect_raw="test",
            effect_evidence_span="test",
            directionality="INVALID",  # type: ignore
            severity_hint="mild",
        )


def test_invalid_source_type():
    with pytest.raises(ValidationError):
        RawItem(
            item_type="tweet",  # type: ignore
            reddit_id="t3_abc",
            subreddit="test",
            url="http://example.com",
            created_utc=0.0,
            score=0,
            body="test",
            comment_depth=0,
            retrieved_at="2026-01-01",
        )
