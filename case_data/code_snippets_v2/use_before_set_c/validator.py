RULES = {
    "non_negative": lambda x: x >= 0,
    "under_limit": lambda x: x < 1000,
    "non_zero": lambda x: x != 0,
}

def get_rules():
    return dict(RULES)

def check_rule(name, value):
    rule = RULES.get(name)
    if rule is None:
        return True
    return rule(value)
