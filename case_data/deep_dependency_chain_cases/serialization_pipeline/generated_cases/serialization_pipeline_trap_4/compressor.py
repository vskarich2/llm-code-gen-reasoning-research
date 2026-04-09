from data import EPOCH_TO_ISO

def compress_node(serialized_records):
    seen = set()
    result = []
    for rec in serialized_records:
        ca = rec["created_at"]
        ca_str = EPOCH_TO_ISO.get(ca, str(ca)) if isinstance(ca, int) else str(ca)
        key = (ca_str, rec["value"])
        if key not in seen:
            seen.add(key)
            out = dict(rec)
            out["created_at"] = ca_str
            result.append(out)
    return result
