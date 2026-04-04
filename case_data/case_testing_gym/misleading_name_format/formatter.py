import time


def format_date(timestamp):
    """Format a date value for display.

    Returns a human-readable date string.
    """
    # BUG: despite the name "format_date", this function is supposed to
    # format UNIX timestamps into "HH:MM:SS" time strings (not dates).
    # The codebase uses "date" loosely to mean "datetime/timestamp".
    # The actual contract (verified by tests) is time formatting.
    t = time.gmtime(timestamp)
    # BUG: uses %Y-%m-%d (date format) instead of %H:%M:%S (time format)
    return time.strftime("%Y-%m-%d", t)


def format_entry(label, timestamp):
    return f"{label}: {format_date(timestamp)}"


def format_log_line(event_name, timestamp, level="INFO"):
    ts = format_date(timestamp)
    return f"[{level}] {ts} - {event_name}"
