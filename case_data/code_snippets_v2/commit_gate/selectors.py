def get_committed_total(st):
    if not st["meta"]["frozen"]:
        return None
    return sum(e.get("val", 0) for e in st["stable"])


def get_view_digest(st):

    return "|".join(e["id"] for e in st["view"])


def get_committed_digest(st):

    if not st["meta"]["frozen"]:
        return None
    return "|".join(e["id"] for e in st["stable"])
