"""Heuristic firsthand-experience signal computation. Pure regex, no LLM."""

from __future__ import annotations

import re

from schemas import FirsthandSignals

_FIRST_PERSON = re.compile(
    r"\b(I|my|me|myself|I'm|I've|I'd|I'll|mine)\b", re.IGNORECASE
)

_SELF_USE_VERBS = re.compile(
    r"\b(I\s+(?:took|take|started|stopped|switched|been on|was on|am on|"
    r"tried|use|using|tapered|titrated|weaned|increased|decreased|"
    r"went on|came off|got on|got off|was prescribed|have been taking|"
    r"have been on|was taking)|"
    r"I've\s+been\s+(?:taking|on|using)|"
    r"I'm\s+(?:on|taking|using|currently on))\b",
    re.IGNORECASE,
)

_SECONDHAND = re.compile(
    r"\b(my (?:friend|mom|dad|sister|brother|wife|husband|partner|patient|"
    r"client|kid|son|daughter|mother|father|girlfriend|boyfriend|roommate)|"
    r"someone I know|a person I|they (?:took|started|tried)|"
    r"(?:he|she) (?:took|started|tried|was on|is on))\b",
    re.IGNORECASE,
)

_ADVICE_ONLY = re.compile(
    r"\b(you should|I'd recommend|I would suggest|have you tried|"
    r"try taking|consider asking|talk to your doctor|ask your doctor|"
    r"you might want to|you could try)\b",
    re.IGNORECASE,
)

_SPECULATION = re.compile(
    r"\b(I think it (?:might|could|may)|probably causes|supposedly|"
    r"I heard that|I read that|from what I've read|apparently)\b",
    re.IGNORECASE,
)


def compute_firsthand_signals(text: str) -> FirsthandSignals:
    """Compute heuristic firsthand signals from text. Pure regex."""
    fp = bool(_FIRST_PERSON.search(text))
    sv = bool(_SELF_USE_VERBS.search(text))
    sh = bool(_SECONDHAND.search(text))
    ao = bool(_ADVICE_ONLY.search(text)) and not sv
    sp = bool(_SPECULATION.search(text)) and not sv

    if sv and not sh:
        score = "strong_yes"
    elif sh and not sv:
        score = "weak_no"
    elif ao and not fp:
        score = "strong_no"
    elif sp and not sv:
        score = "weak_no"
    elif fp and not sh and not ao and not sp:
        score = "weak_yes"
    else:
        score = "neutral"

    return FirsthandSignals(
        has_first_person_pronoun=fp,
        has_self_use_verb=sv,
        has_secondhand_marker=sh,
        has_advice_only_pattern=ao,
        has_speculation_marker=sp,
        heuristic_firsthand_score=score,
    )


def resolve_firsthand(
    heuristic_score: str,
    llm_firsthand: bool,
    llm_confidence: str,
) -> tuple[bool, str]:
    """Apply the hybrid decision table.

    Returns (final_decision: bool, final_confidence: str).
    """
    # strong_yes heuristic: trust heuristic over LLM
    if heuristic_score == "strong_yes":
        if llm_firsthand:
            conf = "high" if llm_confidence in ("high", "medium") else "medium"
            return True, conf
        # Heuristic overrides LLM refusal — self-use verbs are reliable
        return True, "medium"

    # weak_yes
    if heuristic_score == "weak_yes":
        if llm_firsthand:
            conf = "high" if llm_confidence == "high" else "medium"
            return True, conf
        # Borderline: include with low confidence
        return True, "low"

    # neutral
    if heuristic_score == "neutral":
        if llm_firsthand and llm_confidence == "high":
            return True, "medium"
        if llm_firsthand:
            return True, "low"
        return False, "low"

    # weak_no
    if heuristic_score == "weak_no":
        if llm_firsthand and llm_confidence == "high":
            return True, "low"
        return False, "low"

    # strong_no: heuristic is confident this is not firsthand
    if heuristic_score == "strong_no":
        return False, "low"

    # Fallback (should not reach here)
    return False, "low"
