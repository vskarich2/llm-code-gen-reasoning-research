"""Data loader with validation."""

from validator import check_rule

_loaded = None
_load_status = "idle"


def reset():
    global _loaded, _load_status
    _loaded = None
    _load_status = "idle"


def load_and_validate(records, rules):
    """Load records, validating each against rules.

    Returns (valid_records, status) where status reflects outcome.
    """
    global _loaded, _load_status
    valid = []
    for record in records:
        passes = all(check_rule(r, record["value"]) for r in rules)
        if passes:
            valid.append(record)
    _loaded = valid
    _load_status = "validated"
    return valid, _load_status


def get_status():
    return _load_status


def get_loaded():
    return _loaded
