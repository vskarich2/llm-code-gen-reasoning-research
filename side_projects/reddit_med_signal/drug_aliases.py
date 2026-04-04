"""Drug alias resolution from YAML file. No LLM calls."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

_log = logging.getLogger("reddit_med_signal.drug_aliases")

_ALIAS_PATH = Path(__file__).resolve().parent / "config" / "drug_aliases.yaml"


def load_alias_map(path: str | Path | None = None) -> dict[str, list[str]]:
    """Load the drug alias YAML. Returns {canonical: [aliases]}."""
    p = Path(path) if path else _ALIAS_PATH
    if not p.exists():
        _log.warning("Drug alias file not found: %s", p)
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    # Normalize keys and values to lowercase
    alias_map: dict[str, list[str]] = {}
    for canonical, aliases in raw.items():
        key = canonical.lower().strip()
        alias_map[key] = [a.lower().strip() for a in (aliases or [])]
    _log.info("Loaded %d drug alias entries", len(alias_map))
    return alias_map


def resolve_aliases(drug_name: str, alias_map: dict[str, list[str]]) -> list[str]:
    """Return [canonical_name] + aliases for the given drug.

    Case-insensitive lookup. If not found, returns just [drug_name] and logs
    a warning.
    """
    canonical = drug_name.lower().strip()

    # Direct match as canonical key
    if canonical in alias_map:
        result = [canonical] + alias_map[canonical]
        _log.info("Resolved '%s' → %s", drug_name, result)
        return result

    # Check if user provided a brand name that is a value
    for canon, aliases in alias_map.items():
        if canonical in aliases:
            result = [canon] + aliases
            _log.info(
                "Resolved '%s' (brand name) → canonical '%s', aliases %s",
                drug_name, canon, result,
            )
            return result

    _log.warning(
        "No alias expansion found for '%s'. Consider adding to drug_aliases.yaml.",
        drug_name,
    )
    return [canonical]
