"""Utility functions for text matching in T3 evaluators."""


def _low(text: str) -> str:
    return text.lower()


def _has(text: str, terms: list[str]) -> list[str]:
    """Which terms appear (case-insensitive)?"""
    t = _low(text)
    return [term for term in terms if _low(term) in t]
