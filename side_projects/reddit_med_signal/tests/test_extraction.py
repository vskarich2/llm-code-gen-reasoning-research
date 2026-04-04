"""Tests for grounded extraction validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extraction import _validate_grounding


def test_exact_substring_match():
    source = "I had horrible nausea every morning for two weeks."
    span = "horrible nausea every morning"
    assert _validate_grounding(span, source) is True


def test_case_insensitive_match():
    source = "The NAUSEA was unbearable in the first week."
    span = "the nausea was unbearable"
    assert _validate_grounding(span, source) is True


def test_grounding_invalid_hallucinated():
    source = "I felt a bit weird but nothing specific."
    span = "I had severe cognitive impairment and memory loss"
    assert _validate_grounding(span, source) is False


def test_grounding_fuzzy_valid():
    """High word overlap in contiguous window should pass."""
    source = "I lost about fifteen pounds without even trying to diet"
    span = "lost about fifteen pounds without even trying"
    assert _validate_grounding(span, source) is True


def test_empty_span_fails():
    source = "I took the medication daily."
    span = ""
    assert _validate_grounding(span, source) is False


def test_partial_overlap_below_threshold():
    """Low overlap should fail."""
    source = "I had stomach cramps after eating breakfast."
    span = "severe diarrhea and vomiting throughout the day"
    assert _validate_grounding(span, source) is False


def test_grounding_with_minor_differences():
    """Slight rewording should still pass with high overlap."""
    source = "my appetite completely disappeared after starting the medication"
    span = "appetite completely disappeared after starting"
    assert _validate_grounding(span, source) is True
