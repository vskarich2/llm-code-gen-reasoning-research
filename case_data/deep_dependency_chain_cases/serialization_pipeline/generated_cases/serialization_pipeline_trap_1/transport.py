def transport_node(compressed_records):
    coerced = []
    for rec in compressed_records:
        r = dict(rec)
        r["created_at"] = str(r["created_at"])
        coerced.append(r)
    return {
        "sent": len(coerced),
        "records": coerced,
        "timestamps": [r["created_at"] for r in coerced],
        "timestamp_types": ["str"],
    }
