def normalize(entries):
    seen = set()
    out = []
    for e in entries:
        k = e["id"]
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def project(entries):
    return [{"id": e["id"], "label": e.get("label", ""), "val": e.get("val", 0)} for e in entries]


def collapse(entries):
    merged = {}
    for e in entries:
        k = e["id"]
        if k in merged:
            merged[k]["val"] = merged[k]["val"] + e.get("val", 0)
        else:
            merged[k] = dict(e)
    return list(merged.values())


def stage(st, processed):
    st["pending"] = list(processed)
    st["view"] = project(processed)
    st["meta"]["version"] += 1


def commit(st):
    st["stable"] = list(st["pending"])
    st["meta"]["frozen"] = True


def freeze_view(st):
    st["view"] = project(st["stable"])


def materialize(st):
    return {
        "items": list(st["stable"]),
        "display": list(st["view"]),
        "v": st["meta"]["version"],
    }
