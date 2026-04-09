def compress_node(serialized_records):
    seen = set()
    result = []
    for rec in serialized_records:
        key = (str(rec["created_at"]), rec["value"])
        if key not in seen:
            seen.add(key)
            result.append(dict(rec))
    return result
