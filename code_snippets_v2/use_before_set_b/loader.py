"""Data loader with status tracking."""

_status = "idle"
_data = None


def reset():
    global _status, _data
    _status = "idle"
    _data = None


def load(source):
    """Load data from source. Sets status on success only."""
    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    # BUG: on empty/None source, _status stays at previous value
    # instead of being set to "empty"
    return _data


def get_status():
    return _status


def get_data():
    return _data


def validate_format(data):
    """Distractor: checks data format, unrelated to bug."""
    if data is None:
        return False
    return isinstance(data, list)
