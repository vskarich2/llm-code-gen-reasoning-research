def get_committed_total(st):
    """Returns total only if state is committed (frozen). None otherwise."""
    if not st["meta"]["frozen"]:
        return None
    return sum(e.get("val", 0) for e in st["stable"])


def get_view_digest(st):
    """Order-sensitive digest of view items."""
    return "|".join(e["id"] for e in st["view"])


def get_committed_digest(st):
    """Order-sensitive digest of committed items."""
    if not st["meta"]["frozen"]:
        return None
    return "|".join(e["id"] for e in st["stable"])
