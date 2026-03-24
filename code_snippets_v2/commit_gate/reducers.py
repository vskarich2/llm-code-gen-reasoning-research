def normalize(raw):
    return [dict(e) for e in raw]


def collapse(entries):
    merged = {}
    for e in entries:
        merged[e["id"]] = e
    return list(merged.values())


def stage(st, data):
    st["pending"] = list(data)
    st["view"] = list(data)
    st["meta"]["version"] += 1


def commit(st):
    """Promote pending to stable. Sorts by id for canonical ordering. Sets frozen gate."""
    st["stable"] = sorted(st["pending"], key=lambda e: e["id"])
    st["meta"]["frozen"] = True


def freeze_view(st):
    """Rebuild view from committed (stable) data."""
    st["view"] = list(st["stable"])


def materialize(st):
    return list(st["view"])
