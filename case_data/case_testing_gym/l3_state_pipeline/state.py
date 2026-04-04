def make_state(entries):
    return {
        "raw": list(entries),
        "pending": [],
        "stable": [],
        "view": [],
        "meta": {"version": 0, "frozen": False},
    }


def copy_state(st):
    return {
        "raw": list(st["raw"]),
        "pending": list(st["pending"]),
        "stable": list(st["stable"]),
        "view": list(st["view"]),
        "meta": dict(st["meta"]),
    }
