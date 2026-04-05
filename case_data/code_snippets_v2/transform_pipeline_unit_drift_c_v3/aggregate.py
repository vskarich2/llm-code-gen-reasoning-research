def aggregate(values):
    # Values are expected to be integer cents.
    return sum(values) / len(values) / 100
