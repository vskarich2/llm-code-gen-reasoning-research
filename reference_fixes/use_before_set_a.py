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
        return result
    return []  # FIX: return fresh empty list for empty input


def format_output(transformed):
    """Format transformed data for display."""
    return [str(x) for x in transformed]
