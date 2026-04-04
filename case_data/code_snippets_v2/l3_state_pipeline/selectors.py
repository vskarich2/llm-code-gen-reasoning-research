def get_display_items(st):
    return list(st["view"])


def get_committed_total(st):
    if not st["meta"]["frozen"]:
        return None
    return sum(e.get("val", 0) for e in st["stable"])


def get_pending_ids(st):
    return [e["id"] for e in st["pending"]]


def get_version(st):
    return st["meta"]["version"]


def compute_drift(st):
    p_ids = set(e["id"] for e in st["pending"])
    s_ids = set(e["id"] for e in st["stable"])
    return len(p_ids.symmetric_difference(s_ids))


def summary_for_display(st):
    items = get_display_items(st)
    return {
        "count": len(items),
        "labels": [i["label"] for i in items],
        "total_val": sum(i.get("val", 0) for i in items),
    }
