"""Data validation CLAUDE_RULES."""

RULES = {
    "non_negative": lambda x: x >= 0,
    "under_limit": lambda x: x < 1000,
    "non_zero": lambda x: x != 0,
}


def get_rules():
    """Return available validation CLAUDE_RULES."""
    return dict(RULES)


def check_rule(name, value):
    """Check a single rule against a value."""
    rule = RULES.get(name)
    if rule is None:
        return True  # unknown CLAUDE_RULES pass by default
    return rule(value)
