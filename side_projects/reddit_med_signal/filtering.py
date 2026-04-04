"""Heuristic pre-filtering. No LLM calls. Deterministic CLAUDE_RULES only."""

from __future__ import annotations

import logging
import re

from schemas import RawItem

_log = logging.getLogger("reddit_med_signal.filtering")

_BOT_PATTERNS = re.compile(
    r"(AutoModerator|RemindMeBot|sneakpeekbot|RepostSleuthBot|"
    r"TotesMessenger|HelperBot|WikiTextBot|gifv-bot|"
    r"LocationBot|FatFingerHelperBot|\w+Bot$)",
    re.IGNORECASE,
)

# ~1000 common English words for non-English heuristic
_COMMON_ENGLISH = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there",
    "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "me", "when", "make", "can", "like", "time", "no",
    "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then",
    "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "us", "been", "much", "has", "had", "was",
    "is", "are", "am", "were", "did", "does", "don", "didn", "won",
    "more", "very", "really", "still", "too", "thing", "start", "took",
    "feel", "felt", "since", "week", "month", "doctor", "medication",
    "drug", "dose", "side", "effect", "effects", "mg", "taking", "started",
    "stopped", "help", "better", "worse", "symptoms", "pain", "sleep",
    "weight", "anxiety", "depression", "tried", "working", "before",
}

_URL_PATTERN = re.compile(r"https?://\S+")


def _is_too_short(item: RawItem, min_length: int) -> bool:
    return len(item.body.strip()) < min_length


def _is_deleted(item: RawItem) -> bool:
    stripped = item.body.strip().lower()
    return stripped in ("[deleted]", "[removed]", "")


def _is_bot(item: RawItem) -> bool:
    if item.author is None:
        return False
    return bool(_BOT_PATTERNS.search(item.author))


def _is_url_spam(item: RawItem, max_url_fraction: float) -> bool:
    urls = _URL_PATTERN.findall(item.body)
    url_chars = sum(len(u) for u in urls)
    total = len(item.body.strip())
    if total == 0:
        return True
    return (url_chars / total) > max_url_fraction


def _is_non_english(item: RawItem) -> bool:
    words = re.findall(r"[a-zA-Z]+", item.body.lower())
    if len(words) < 5:
        return False  # too short to judge
    english_count = sum(1 for w in words if w in _COMMON_ENGLISH)
    return (english_count / len(words)) < 0.3


def apply_heuristic_filters(
    items: list[RawItem],
    cfg: dict,
) -> list[RawItem]:
    """Apply all heuristic filters. Returns passing items.

    Logs each drop reason and counts.
    """
    filter_cfg = cfg.get("filtering", {})
    min_len = filter_cfg.get("min_body_length", 30)
    max_url_frac = filter_cfg.get("max_url_fraction", 0.8)
    max_after = filter_cfg.get("max_items_after_heuristic", 400)

    passed: list[RawItem] = []
    drop_counts: dict[str, int] = {
        "short": 0, "deleted": 0, "bot": 0,
        "url_spam": 0, "non_english": 0,
    }

    for item in items:
        if _is_deleted(item):
            drop_counts["deleted"] += 1
            continue
        if _is_too_short(item, min_len):
            drop_counts["short"] += 1
            continue
        if _is_bot(item):
            drop_counts["bot"] += 1
            continue
        if _is_url_spam(item, max_url_frac):
            drop_counts["url_spam"] += 1
            continue
        if _is_non_english(item):
            drop_counts["non_english"] += 1
            continue
        passed.append(item)

    total_dropped = sum(drop_counts.values())
    _log.info(
        "Heuristic filter: %d → %d items (%d dropped: %s)",
        len(items), len(passed), total_dropped, drop_counts,
    )

    # Enforce hard cap: prioritize by body length (longer = more extractable)
    if len(passed) > max_after:
        _log.warning(
            "Post-filter count %d exceeds cap %d; truncating by body length",
            len(passed), max_after,
        )
        passed.sort(key=lambda x: len(x.body), reverse=True)
        passed = passed[:max_after]

    return passed
