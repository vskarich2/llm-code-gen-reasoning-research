def compress_node(serialized_records):
    seen = set()
    result = []
    for rec in serialized_records:
        ca_field = "created_at_iso" if "created_at_iso" in rec else "created_at"
        key = (str(rec[ca_field]), rec["value"])
        if key not in seen:
            seen.add(key)
            out = dict(rec)
            if "created_at_iso" in rec:
                out["created_at"] = rec["created_at_iso"]
            result.append(out)
    return result
