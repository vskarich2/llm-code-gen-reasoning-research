"""Data transformation pipeline."""

_last_result = []


def transform(data):
    """Transform input data, returning processed results.

    Must always return a fresh list for the given input.
    """
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    # BUG: when data is empty/falsy, returns stale _last_result
    # instead of a fresh empty list
    return _last_result


def format_output(transformed):
    """Format transformed data for display."""
    return [str(x) for x in transformed]
