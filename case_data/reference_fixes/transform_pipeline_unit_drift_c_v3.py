"""Reference fix: convert dollars to cents in to_internal."""


def to_internal(x):
    # Downstream aggregation consumes integer cents.
    return int(round(x * 100))
