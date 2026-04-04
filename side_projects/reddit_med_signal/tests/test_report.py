"""Tests for report generation — disclaimer presence and language checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report import (
    DISCLAIMER_FOOTER,
    DISCLAIMER_HEADER,
    _build_reliability_section,
    _build_skepticism_section,
)
from schemas import AggregationResult, ConflictRecord, ConflictType, EffectTheme


def _make_result(**kwargs) -> AggregationResult:
    defaults = {
        "drug_query": "metformin",
        "canonical_drug_name": "metformin",
        "total_raw_items": 100,
        "total_after_heuristic_filter": 80,
        "total_extraction_attempted": 80,
        "total_extraction_succeeded": 75,
        "total_extraction_failed": 5,
        "total_firsthand_high": 50,
        "total_firsthand_medium": 10,
        "total_firsthand_low": 5,
        "total_excluded": 10,
        "is_sparse": False,
        "run_timestamp": "20260402_120000",
    }
    defaults.update(kwargs)
    return AggregationResult(**defaults)


def test_disclaimer_header_content():
    assert "NOT medical advice" in DISCLAIMER_HEADER
    assert "NOT prevalence estimates" in DISCLAIMER_HEADER


def test_disclaimer_footer_content():
    assert "auto-generated from Reddit" in DISCLAIMER_FOOTER
    # Check for key phrases (may be split across lines)
    footer_flat = DISCLAIMER_FOOTER.replace("\n", " ")
    assert "background situational awareness" in footer_flat


def test_reliability_section_present():
    result = _make_result()
    section = _build_reliability_section(result)
    assert "Data Reliability" in section
    assert "Items retrieved" in section
    assert "Extraction failures" in section
    assert "5" in section  # extraction failures count


def test_reliability_shows_unmapped():
    result = _make_result(unmapped_labels=["jaw_clenching", "vivid_dreams"])
    section = _build_reliability_section(result)
    assert "jaw_clenching" in section
    assert "vivid_dreams" in section
    assert "Unmapped effect labels" in section


def test_sparse_warning():
    result = _make_result(
        is_sparse=True,
        total_firsthand_high=3,
        total_firsthand_medium=2,
        total_firsthand_low=1,
    )
    section = _build_reliability_section(result)
    assert "Sparse case_data warning" in section


def test_no_prevalence_language():
    result = _make_result()
    section = _build_reliability_section(result)
    forbidden = ["prevalence", "% of users", "common", "frequent", "rare"]
    for word in forbidden:
        assert word not in section.lower(), f"Found forbidden word: {word}"


def test_skepticism_section_low_sample():
    result = _make_result(
        total_firsthand_high=3,
        total_firsthand_medium=2,
        total_firsthand_low=1,
    )
    section = _build_skepticism_section(result)
    assert "few firsthand reports" in section.lower() or "small sample" in section.lower()


def test_skepticism_section_high_low_confidence():
    result = _make_result(
        total_firsthand_high=10,
        total_firsthand_medium=5,
        total_firsthand_low=20,
    )
    section = _build_skepticism_section(result)
    assert "uncertainty" in section.lower() or "low" in section.lower()


def test_skepticism_section_extraction_failures():
    result = _make_result(
        total_extraction_attempted=100,
        total_extraction_failed=15,
    )
    section = _build_skepticism_section(result)
    assert "extraction failure" in section.lower()


def test_conflict_type_labels_in_conflicts():
    """Verify the conflict taxonomy uses proper labels."""
    conflict = ConflictRecord(
        effect_a="insomnia",
        effect_b="drowsiness",
        conflict_type=ConflictType.TEMPORAL_VARIATION,
        evidence_summary="Temporal pattern detected",
        count_a=10,
        count_b=8,
    )
    assert conflict.conflict_type.value == "temporal_variation"
    assert conflict.conflict_type != ConflictType.DIRECT_CONTRADICTION
