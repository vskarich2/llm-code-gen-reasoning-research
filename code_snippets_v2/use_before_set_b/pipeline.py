"""Data pipeline that uses loader."""

from loader import load, get_status, get_data


def reset():
    global _status, _data
    _status = "idle"
    _data = None


def run_pipeline(source):
    """Load data and return status-tagged result.

    Contract: status must reflect THIS call's outcome,
    not a previous call's state.
    """
    load(source)
    status = get_status()
    data = get_data()

    return {
        "status": status,
        "count": len(data) if data else 0,
        "data": data,
    }
