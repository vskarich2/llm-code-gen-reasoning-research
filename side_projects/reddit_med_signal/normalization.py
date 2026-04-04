"""Deterministic effect label normalization. No LLM calls.

Pipeline: LLM effect_raw → clean_label → synonym_map lookup → effect_normalized
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from schemas import ExtractedRecord

_log = logging.getLogger("reddit_med_signal.normalization")

_SYNONYM_PATH = Path(__file__).resolve().parent / "config" / "effect_synonyms.yaml"


def load_synonym_map(path: str | Path | None = None) -> dict[str, list[str]]:
    """Load the effect synonyms YAML. Returns {canonical: [variants]}."""
    p = Path(path) if path else _SYNONYM_PATH
    if not p.exists():
        _log.warning("Synonym map not found: %s — normalization will be minimal", p)
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    # Normalize all keys and values to lowercase
    result: dict[str, list[str]] = {}
    for canonical, variants in raw.items():
        key = canonical.lower().strip()
        result[key] = [v.lower().strip() for v in (variants or [])]
    total_variants = sum(len(v) for v in result.values())
    _log.info(
        "Loaded synonym map: %d canonical labels, %d total variants",
        len(result), total_variants,
    )
    return result


def clean_label(raw: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace to underscores."""
    label = raw.lower().strip()
    label = re.sub(r"[^a-z0-9_\s]", "", label)
    label = re.sub(r"\s+", "_", label)
    label = label.strip("_")
    return label


def canonicalize_effect(
    raw_label: str, synonym_map: dict[str, list[str]]
) -> tuple[str, bool]:
    """Map a raw LLM label to its canonical form.

    Returns (canonical_label, was_mapped).
    If no match, returns the cleaned raw label and was_mapped=False.
    """
    cleaned = clean_label(raw_label)

    # Direct match to a canonical key
    if cleaned in synonym_map:
        return cleaned, True

    # Match to a synonym value
    for canonical, variants in synonym_map.items():
        if cleaned in variants:
            return canonical, True

    # No match — return cleaned as-is
    return cleaned, False


def normalize_records(
    records: list[ExtractedRecord],
    synonym_map: dict[str, list[str]],
) -> tuple[list[ExtractedRecord], list[str]]:
    """Normalize all effect labels in all records.

    Returns (records, unmapped_labels).
    Mutates records in-place for efficiency.
    """
    unmapped: set[str] = set()
    total_effects = 0
    total_mapped = 0

    for record in records:
        for effect in record.reported_effects:
            canonical, was_mapped = canonicalize_effect(
                effect.effect_raw, synonym_map
            )
            effect.effect_normalized = canonical
            total_effects += 1
            if was_mapped:
                total_mapped += 1
            else:
                unmapped.add(canonical)

    unmapped_list = sorted(unmapped)
    _log.info(
        "Normalization: %d effects, %d mapped (%.0f%%), %d unmapped labels: %s",
        total_effects, total_mapped,
        (total_mapped / max(total_effects, 1)) * 100,
        len(unmapped_list), unmapped_list,
    )
    return records, unmapped_list
