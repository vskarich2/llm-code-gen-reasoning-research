"""Case 8 (C): Serialization pipeline.

Chain: record_builder → serializer → compressor → transport
Bypass: get_serialized reads serializer output directly for debug logging
Bug: serializer encodes timestamps as epoch seconds (int) instead of ISO strings,
     breaking downstream compressor's dedup which uses string comparison
Canonical field: serialized record's "created_at" field
"""

from data.deep_dependency_chain.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

RECORDS = {
    "primary": [
        {"id": "r1", "name": "Alice", "created_at": "2026-04-01T10:00:00", "value": 100},
        {"id": "r2", "name": "Bob", "created_at": "2026-04-01T10:00:00", "value": 200},
        {"id": "r3", "name": "Carol", "created_at": "2026-04-02T08:30:00", "value": 150},
    ],
    "alternate_dedup": [
        {"id": "r4", "name": "Dave", "created_at": "2026-04-01T10:00:00", "value": 300},
        {"id": "r5", "name": "Eve", "created_at": "2026-04-01T10:00:00", "value": 300},
    ],
    "trap_catching_input": [
        {"id": "r6", "name": "Frank", "created_at": "2026-04-03T15:45:00", "value": 50},
    ],
}

# Epoch conversion helpers
def _iso_to_epoch(iso_str):
    # Simple parser for "YYYY-MM-DDTHH:MM:SS"
    from datetime import datetime
    dt = datetime.fromisoformat(iso_str)
    return int(dt.timestamp())

def _epoch_to_iso(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _build_records(dataset):
    return [dict(r) for r in RECORDS[dataset]]


def _serialize_buggy(record):
    """BUG: encodes created_at as epoch int instead of ISO string."""
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": _iso_to_epoch(record["created_at"]),  # BUG: int, not string
        "value": record["value"],
    }


def _serialize_fixed(record):
    """ROOT FIX: keeps created_at as ISO string."""
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": record["created_at"],  # preserve ISO string
        "value": record["value"],
    }


def _serialize_trap5(record):
    """TRAP 5: adds created_at_iso alongside epoch created_at."""
    result = _serialize_buggy(record)
    result["created_at_iso"] = record["created_at"]
    return result


def _serialize_reconvert(record):
    """TRAP 3: serializer converts to epoch then back to ISO using a different format.
    Result: '2026-04-01 10:00:00' (space separator) instead of '2026-04-01T10:00:00' (T separator).
    Passes type checks (it's a string) but fails ISO format validation."""
    epoch = _iso_to_epoch(record["created_at"])
    from datetime import datetime, timezone
    reconverted = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": reconverted,  # space instead of T
        "value": record["value"],
    }


def _compress(serialized_records, *, use_iso_field=False):
    """Deduplicates records by (created_at, value) pair using string comparison."""
    seen = set()
    result = []
    for rec in serialized_records:
        ca_field = "created_at_iso" if use_iso_field and "created_at_iso" in rec else "created_at"
        key = (str(rec[ca_field]), rec["value"])
        if key not in seen:
            seen.add(key)
            out = dict(rec)
            if use_iso_field and "created_at_iso" in rec:
                out["created_at"] = rec["created_at_iso"]  # replace epoch with ISO in output
            result.append(out)
    return result


def _compress_type_aware(serialized_records):
    """TRAP 4: compressor converts epoch→ISO in both dedup keys AND output records.
    Downstream override — serializer untouched but output has ISO strings."""
    seen = set()
    result = []
    for rec in serialized_records:
        ca = rec["created_at"]
        if isinstance(ca, int):
            ca_str = _epoch_to_iso(ca)
        else:
            ca_str = str(ca)
        key = (ca_str, rec["value"])
        if key not in seen:
            seen.add(key)
            out = dict(rec)
            out["created_at"] = ca_str  # replace epoch with ISO in output
            result.append(out)
    return result


def _transport(compressed_records):
    """Sends records and returns delivery report."""
    return {
        "sent": len(compressed_records),
        "records": compressed_records,
        "timestamps": [r["created_at"] for r in compressed_records],
        "timestamp_types": list(set(type(r["created_at"]).__name__ for r in compressed_records)),
    }


def _transport_coerced(compressed_records):
    """TRAP 1: transport converts all timestamps to strings before sending."""
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
        "coerced": True,
    }


def _get_serialized(serialized_records):
    """BYPASS CONSUMER: reads serialized records directly for debug logging.
    Debug log needs ISO timestamp strings for human readability."""
    return [{"id": r["id"], "created_at": r["created_at"],
             "created_at_type": type(r["created_at"]).__name__}
            for r in serialized_records]


# ── Dispatch ──

def _run_chain(patch_id, dataset="primary"):
    records = _build_records(dataset)

    # Step A: serialize
    if patch_id == "root_fix":
        serialized = [_serialize_fixed(r) for r in records]
    elif patch_id == "trap_5":
        serialized = [_serialize_trap5(r) for r in records]
    elif patch_id == "trap_3":
        serialized = [_serialize_reconvert(r) for r in records]
    else:
        serialized = [_serialize_buggy(r) for r in records]

    # Bypass
    debug_log = _get_serialized(serialized)

    # Step B: compress
    if patch_id == "trap_4":
        compressed = _compress_type_aware(serialized)
    elif patch_id == "trap_5":
        compressed = _compress(serialized, use_iso_field=True)
    else:
        compressed = _compress(serialized)

    # Step C: transport
    if patch_id == "trap_1":
        report = _transport_coerced(compressed)
    else:
        report = _transport(compressed)

    return {
        "report": report,
        "debug_log": debug_log,
        "serialized": serialized,
        "compressed": compressed,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    report = r["report"]
    # Primary: 3 records. r1 and r2 share (2026-04-01T10:00:00, but different values 100 vs 200).
    # No dedup should happen (values differ). All 3 should be sent.
    # Timestamps must be strings (ISO format) in the transport output.
    if report["sent"] != 3:
        return False
    if "str" not in report["timestamp_types"]:
        return False
    return True


def _run_invariant_trap_catching(patch_id):
    """Single record — transport timestamp must be ISO string, not epoch string.
    Trap_1 coerces to str: epoch 1743685500 → "1743685500" (not ISO).
    Correct: "2026-04-03T15:45:00"."""
    r = _run_chain(patch_id, "trap_catching_input")
    report = r["report"]
    if report["sent"] != 1:
        return False, f"sent={report['sent']}, expected=1", "single_record"
    ts = report["timestamps"][0]
    # Must look like ISO, not like an epoch number
    is_iso = isinstance(ts, str) and "T" in ts and len(ts) >= 19
    return is_iso, f"timestamp={ts!r}, is_iso={is_iso}", "iso_format_check"


def _run_invariant_generalization(patch_id):
    """Dedup test: r4 and r5 have same created_at and same value → should dedup to 1.
    With ISO strings: key = ("2026-04-01T10:00:00", 300) → dedup works → 1 record.
    With epoch ints: key = (str(1743505200), 300) → also deduplicates → 1 record.
    So dedup count is the same either way. Need a case where dedup differs.

    Actually the dedup works the same because str(epoch) is deterministic.
    The real generalization issue: trap_3 (heuristic) fails for date-only strings.

    Use a record with date-only created_at "2026-04-01" (no T).
    Trap_3: no T in string → converts to epoch → int. Loses the date format.
    Root fix: preserves as-is.
    """
    # Test with date-only input appended to alternate_dedup
    # Actually I need to test trap_3 specifically. Let me check what trap_3 does:
    # trap_3: if 'T' in created_at → preserve. else → epoch-convert.
    # I can't easily add a date-only record to existing datasets without changing schema.
    #
    # Simpler: test that the transport output has proper ISO format for ALL records.
    # Trap_3 works for standard ISO (has T). But what about records where
    # created_at was already epoch (from some other source)?
    # Not relevant — all our records have ISO strings.
    #
    # Alternative generalization: use alternate_dedup dataset.
    # r4 and r5 have same timestamp and value. Should dedup to 1 record.
    r = _run_chain(patch_id, "alternate_dedup")
    report = r["report"]
    # Both have created_at="2026-04-01T10:00:00" and value=300 → 1 unique
    passed = report["sent"] == 1
    return passed, f"sent={report['sent']}, expected=1 (dedup)", "dedup_check"


def _run_invariant_causal_location(patch_id):
    """Serialized created_at must be ISO string, not epoch int."""
    r = _run_chain(patch_id, "primary")
    for sr in r["serialized"]:
        ca = sr["created_at"]
        if not isinstance(ca, str):
            return False, f"id={sr['id']}: created_at={ca!r} (type={type(ca).__name__}), expected str", None
        if "T" not in ca:
            return False, f"id={sr['id']}: created_at={ca!r} missing 'T' (not ISO)", None
    return True, "all serialized timestamps are ISO strings", None


def _run_invariant_cross_path(patch_id):
    """Debug log (bypass) created_at type must match transport created_at type.
    If compressor/transport fix the type but serializer still outputs epoch,
    debug log shows int while transport shows string."""
    r = _run_chain(patch_id, "primary")
    debug_types = set(d["created_at_type"] for d in r["debug_log"])
    transport_types = set(r["report"]["timestamp_types"])
    consistent = debug_types == transport_types
    return consistent, f"debug_types={debug_types}, transport_types={transport_types}", None


def _run_invariant_chain_integrity(patch_id):
    """Compressed record created_at must match serialized record created_at.
    If compressor converts types internally, the compressed output won't
    match the serializer output."""
    r = _run_chain(patch_id, "primary")
    serial_map = {sr["id"]: sr["created_at"] for sr in r["serialized"]}
    for cr in r["compressed"]:
        serial_ca = serial_map.get(cr["id"])
        if serial_ca is not None and cr["created_at"] != serial_ca:
            return False, (f"id={cr['id']}: serialized={serial_ca!r}, "
                           f"compressed={cr['created_at']!r}"), None
    return True, "compressed timestamps match serialized", None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="serialization_pipeline_chain",
        difficulty="C",
        domain="case_data serialization",
        scenario="Record serializer encodes created_at as epoch int instead of ISO "
                 "string. Downstream compressor's string-based dedup and transport's "
                 "output format break.",
        nodes=NodeDeclarations(
            source_of_truth_node="record_builder",
            corruption_introduced_at_node="serializer",
            first_observable_symptom_node="compressor",
            required_fix_node="serializer",
        ),
        canonical=CanonicalRepresentation(
            field_names=["created_at"],
            schema_description="str, ISO 8601 format 'YYYY-MM-DDTHH:MM:SS'",
            storage_location="serialized record dicts from serializer",
            access_paths=[
                "compressor reads created_at for dedup key",
                "transport reads created_at for output",
                "get_serialized reads created_at directly (BYPASS for debug log)",
            ],
        ),
        chain=[
            ChainNode("record_builder", "builder.py", "build_records",
                      "constructs record dicts from source case_data"),
            ChainNode("serializer", "serializer.py", "serialize",
                      "serializes records — BUG: epoch int instead of ISO string"),
            ChainNode("compressor", "compressor.py", "compress",
                      "deduplicates records by (created_at, value) string key"),
            ChainNode("transport", "transport.py", "transport",
                      "sends compressed records, includes timestamps in report"),
        ],
        bypass_consumer="get_serialized",
        bypass_description="reads created_at directly from serialized records for debug log; "
                           "no compressor/transport calls; no shared logic",
        bug_description="serializer converts created_at to epoch int. Compressor's string-based "
                        "dedup uses str(epoch) which works differently than ISO string comparison. "
                        "Transport outputs epoch ints instead of readable timestamps.",
        root_fix_description="preserve created_at as ISO string in serializer",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "transport coerces all timestamps to strings before sending",
                     "str(created_at) → '1743505200' instead of '2026-04-01T10:00:00'",
                     "transport output has string timestamps (satisfies type check)",
                     "debug log (bypass) still shows int type; inconsistent with transport",
                     "cross_path", None),
            TrapSpec("trap_3", "validation_masking", "C",
                     "serializer converts to epoch then back with space separator",
                     "epoch→strftime('%Y-%m-%d %H:%M:%S') → space instead of T",
                     "produces string type timestamps (passes type check)",
                     "output format '2026-04-03 15:45:00' is not ISO (missing T separator)",
                     "trap_catching", "iso_format_check"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "compressor converts epoch→ISO before dedup key construction",
                     "if isinstance(int): epoch_to_iso() before making key",
                     "correct dedup behavior",
                     "debug log (bypass) still shows epoch ints",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "serializer adds created_at_iso alongside epoch created_at",
                     "record['created_at_iso'] = iso_string; created_at stays epoch",
                     "correct ISO available for compressor to use",
                     "debug log reads created_at (epoch), not created_at_iso",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "transport timestamp must be ISO format (contain 'T'), not epoch string",
                          [{"desc": "single record ISO check"}]),
            InvariantSpec("generalization",
                          "records with same timestamp+value must dedup to 1",
                          [{"desc": "dedup correctness"}]),
            InvariantSpec("causal_location",
                          "serialized created_at must be ISO string type, not int",
                          [{"desc": "serializer output type check"}]),
            InvariantSpec("cross_path",
                          "debug log timestamp type must match transport timestamp type",
                          [{"desc": "debug vs transport type consistency"}]),
            InvariantSpec("chain_integrity",
                          "compressed created_at must match serialized created_at",
                          [{"desc": "serializer-compressor value consistency"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
