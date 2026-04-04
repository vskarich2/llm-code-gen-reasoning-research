"""Tests for heuristic pre-filtering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filtering import apply_heuristic_filters
from schemas import RawItem

_CFG = {"filtering": {"min_body_length": 30, "max_url_fraction": 0.8, "max_items_after_heuristic": 400}}


def _item(body: str, author: str = "user123") -> RawItem:
    return RawItem(
        item_type="post",
        reddit_id="t3_test",
        subreddit="test",
        url="http://example.com",
        author=author,
        created_utc=1000.0,
        score=5,
        title="Test",
        body=body,
        comment_depth=0,
        retrieved_at="2026-01-01",
    )


def test_short_text_dropped():
    items = [_item("too short")]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 0


def test_deleted_dropped():
    items = [_item("[deleted]"), _item("[removed]")]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 0


def test_bot_dropped():
    items = [_item("This is a long enough body for the filter to accept it normally", author="AutoModerator")]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 0


def test_url_spam_dropped():
    body = "https://example.com/very/long/url/that/takes/up/most/of/the/content"
    items = [_item(body)]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 0


def test_valid_item_passes():
    body = "I've been on metformin for about three months now and the nausea was rough at first but got better."
    items = [_item(body)]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 1


def test_empty_body_dropped():
    items = [_item("")]
    result = apply_heuristic_filters(items, _CFG)
    assert len(result) == 0
