def make_state(entries):
    return {
        "raw": list(entries),
        "pending": [],
        "stable": [],
        "view": [],
        "meta": {"version": 0, "frozen": False},
    }
