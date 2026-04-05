"""Data transformation pipeline."""

_last_result = []


def transform(data):
    """Transform input case_data, returning processed results.

    Must always return a fresh list for the given input.
    """
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    return _last_result


def format_output(transformed):
    """Format transformed case_data for display."""
    return [str(x) for x in transformed]
