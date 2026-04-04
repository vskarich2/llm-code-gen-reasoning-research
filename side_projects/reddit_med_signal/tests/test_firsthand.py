"""Tests for heuristic firsthand classification and decision table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firsthand import compute_firsthand_signals, resolve_firsthand


def test_strong_yes_self_use_verb():
    signals = compute_firsthand_signals(
        "I've been taking metformin for 3 months and it changed my life."
    )
    assert signals.has_self_use_verb is True
    assert signals.has_first_person_pronoun is True
    assert signals.heuristic_firsthand_score == "strong_yes"


def test_strong_no_secondhand():
    signals = compute_firsthand_signals(
        "My friend tried Zoloft and hated it. She stopped after a week."
    )
    assert signals.has_secondhand_marker is True
    assert signals.heuristic_firsthand_score == "weak_no"


def test_weak_yes_first_person_no_verb():
    signals = compute_firsthand_signals(
        "My experience with Lexapro has been ok overall."
    )
    assert signals.has_first_person_pronoun is True
    assert signals.heuristic_firsthand_score == "weak_yes"


def test_advice_only():
    signals = compute_firsthand_signals(
        "You should definitely try taking it with food. Ask your doctor about timing."
    )
    assert signals.has_advice_only_pattern is True
    assert signals.heuristic_firsthand_score == "strong_no"


def test_speculation():
    signals = compute_firsthand_signals(
        "I think it might cause weight gain based on what I read that online."
    )
    assert signals.has_speculation_marker is True
    assert signals.heuristic_firsthand_score == "weak_no"


def test_mixed_signals_self_use_and_secondhand():
    signals = compute_firsthand_signals(
        "I took metformin and my friend did too. We both had nausea."
    )
    assert signals.has_self_use_verb is True
    assert signals.has_secondhand_marker is True
    # self_use_verb + secondhand → strong_yes (sv and not sh would fail,
    # but sv is true and sh is true, so it falls through to neutral)
    # Actually: sv=True, sh=True → first condition "sv and not sh" is False
    # Falls through to "neutral"
    assert signals.heuristic_firsthand_score == "neutral"


# Decision table tests

def test_decision_strong_yes_llm_yes_high():
    final, conf = resolve_firsthand("strong_yes", True, "high")
    assert final is True
    assert conf == "high"


def test_decision_strong_yes_llm_no():
    """Heuristic overrides LLM refusal for strong_yes."""
    final, conf = resolve_firsthand("strong_yes", False, "high")
    assert final is True
    assert conf == "medium"


def test_decision_strong_no_llm_yes():
    """Heuristic strong_no overrides LLM even when LLM says yes."""
    final, conf = resolve_firsthand("strong_no", True, "high")
    assert final is False


def test_decision_neutral_llm_yes_high():
    final, conf = resolve_firsthand("neutral", True, "high")
    assert final is True
    assert conf == "medium"


def test_decision_neutral_llm_no():
    final, conf = resolve_firsthand("neutral", False, "high")
    assert final is False


def test_decision_weak_yes_llm_no():
    """Borderline: include with low confidence."""
    final, conf = resolve_firsthand("weak_yes", False, "high")
    assert final is True
    assert conf == "low"


def test_decision_weak_no_llm_yes_high():
    """LLM high confidence + weak heuristic negative → flag as low."""
    final, conf = resolve_firsthand("weak_no", True, "high")
    assert final is True
    assert conf == "low"


def test_decision_weak_no_llm_yes_medium():
    final, conf = resolve_firsthand("weak_no", True, "medium")
    assert final is False
