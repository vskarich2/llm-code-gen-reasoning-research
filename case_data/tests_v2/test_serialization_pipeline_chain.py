"""Tests for serialization_pipeline_chain.

Bug: serializer converts created_at to epoch int instead of ISO string.
     Transport outputs unreadable epoch ints.
Fix: preserve created_at as ISO string in serialize().
"""


def test(mod):
    errors = []

    build_records_node = getattr(mod, "build_records_node", None)
    serialize = getattr(mod, "serialize", None)
    compress_node = getattr(mod, "compress_node", None)
    transport_node = getattr(mod, "transport_node", None)
    if not build_records_node or not serialize or not compress_node or not transport_node:
        return False, ["required functions not found: build_records_node, serialize, compress_node, transport_node"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    if RAW_DATA is None:
        return False, ["RAW_DATA not found in module"]

    # Invariant 1: serialized created_at must be ISO string
    records = build_records_node(RAW_DATA["primary"])
    serialized = serialize(records)
    for sr in serialized:
        ca = sr["created_at"]
        if not isinstance(ca, str):
            errors.append(f"invariant 1: id={sr['id']} created_at={ca!r} (type {type(ca).__name__}), expected str")
        elif "T" not in ca:
            errors.append(f"invariant 1: id={sr['id']} created_at={ca!r} missing 'T' (not ISO format)")

    # Invariant 2: transport timestamps are ISO strings
    compressed = compress_node(serialized)
    report = transport_node(compressed)
    if report["sent"] != 3:
        errors.append(f"invariant 2: sent={report['sent']}, expected 3")
    for ts in report["timestamps"]:
        if not isinstance(ts, str) or "T" not in ts:
            errors.append(f"invariant 2: transport timestamp={ts!r} is not ISO string")
            break

    # Invariant 3: dedup_pair (same ts + value) deduplicates to 1 record
    records_dedup = build_records_node(RAW_DATA["dedup_pair"])
    serialized_dedup = serialize(records_dedup)
    compressed_dedup = compress_node(serialized_dedup)
    report_dedup = transport_node(compressed_dedup)
    if report_dedup["sent"] != 1:
        errors.append(f"invariant 3: dedup_pair sent={report_dedup['sent']}, expected 1")

    # Invariant 4: compress must not mutate created_at (chain integrity)
    if not errors:
        serial_map = {sr["id"]: sr["created_at"] for sr in serialized}
        for cr in compressed:
            if cr["id"] in serial_map and cr["created_at"] != serial_map[cr["id"]]:
                errors.append(
                    f"invariant 4: id={cr['id']} compressed={cr['created_at']!r} "
                    f"!= serialized={serial_map[cr['id']]!r}"
                )

    return not errors, errors
