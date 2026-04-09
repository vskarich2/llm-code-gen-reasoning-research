def transport_node(compressed_records):
    ts_types = set()
    for r in compressed_records:
        ts_types.add("int" if isinstance(r["created_at"], int) else "str")
    return {
        "sent": len(compressed_records),
        "records": compressed_records,
        "timestamps": [r["created_at"] for r in compressed_records],
        "timestamp_types": list(ts_types),
    }
