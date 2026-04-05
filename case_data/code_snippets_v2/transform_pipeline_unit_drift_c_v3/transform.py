def to_internal(x):
    # Intended contract: downstream aggregation consumes cents.
    return int(x)
