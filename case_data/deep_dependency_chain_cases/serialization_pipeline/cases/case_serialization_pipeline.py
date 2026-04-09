"""Case 8 (C): Serialization pipeline.

Chain: record_builder → serializer → compressor → transport
Bypass: get_serialized reads serializer output directly for debug logging
Bug: serializer encodes timestamps as epoch seconds (int) instead of ISO strings,
     breaking downstream compressor's dedup which uses string comparison
Canonical field: serialized record's "created_at" field
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

EPOCH_TABLE = {
    "2026-04-01T10:00:00": 1743501600,
    "2026-04-02T08:30:00": 1743583800,
    "2026-04-03T15:45:00": 1743695100,
}

EPOCH_TO_ISO = {v: k for k, v in EPOCH_TABLE.items()}

RAW_DATA = {
    "primary": [
        {"id": "r1", "name": "Alice", "created_at": "2026-04-01T10:00:00", "value": 100},
        {"id": "r2", "name": "Bob",   "created_at": "2026-04-01T10:00:00", "value": 200},
        {"id": "r3", "name": "Carol", "created_at": "2026-04-02T08:30:00", "value": 150},
    ],
    "dedup_pair": [
        {"id": "r4", "name": "Dave", "created_at": "2026-04-01T10:00:00", "value": 300},
        {"id": "r5", "name": "Eve",  "created_at": "2026-04-01T10:00:00", "value": 300},
    ],
    "single": [
        {"id": "r6", "name": "Frank", "created_at": "2026-04-03T15:45:00", "value": 50},
    ],
}

CASE_DATA_GLOBALS = ["RAW_DATA", "EPOCH_TABLE", "EPOCH_TO_ISO"]


def _build_records(dataset):
    return [dict(r) for r in RAW_DATA[dataset]]


def _serialize_buggy(record):
    """BUG: encodes created_at as epoch int instead of ISO string."""
    iso = record["created_at"]
    epoch = EPOCH_TABLE.get(iso, 0)
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": epoch,
        "value": record["value"],
    }


def _serialize_fixed(record):
    """ROOT FIX: keeps created_at as ISO string."""
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": record["created_at"],
        "value": record["value"],
    }


def _serialize_trap5(record):
    """TRAP 5: adds created_at_iso alongside epoch created_at."""
    result = _serialize_buggy(record)
    result["created_at_iso"] = record["created_at"]
    return result


def _serialize_reconvert(record):
    """TRAP 3: converts to epoch then back with space separator instead of T."""
    iso = record["created_at"]
    epoch = EPOCH_TABLE.get(iso, 0)
    reconverted = EPOCH_TO_ISO.get(epoch, str(epoch)).replace("T", " ")
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": reconverted,
        "value": record["value"],
    }


def _compress(serialized_records, *, use_iso_field=False):
    seen = set()
    result = []
    for rec in serialized_records:
        ca_field = "created_at_iso" if use_iso_field and "created_at_iso" in rec else "created_at"
        key = (str(rec[ca_field]), rec["value"])
        if key not in seen:
            seen.add(key)
            out = dict(rec)
            if use_iso_field and "created_at_iso" in rec:
                out["created_at"] = rec["created_at_iso"]
            result.append(out)
    return result


def _compress_type_aware(serialized_records):
    """TRAP 4: compressor converts epoch→ISO in both dedup keys AND output records."""
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


def _transport(compressed_records):
    ts_types = set()
    for r in compressed_records:
        ts_types.add("int" if isinstance(r["created_at"], int) else "str")
    return {
        "sent": len(compressed_records),
        "records": compressed_records,
        "timestamps": [r["created_at"] for r in compressed_records],
        "timestamp_types": list(ts_types),
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
    """BYPASS CONSUMER: reads serialized records directly for debug logging."""
    return [{"id": r["id"], "created_at": r["created_at"],
             "created_at_type": "int" if isinstance(r["created_at"], int) else "str"}
            for r in serialized_records]


# ── Dispatch ──

def _run_chain(patch_id, dataset="primary"):
    records = _build_records(dataset)

    if patch_id == "root_fix":
        serialized = [_serialize_fixed(r) for r in records]
    elif patch_id == "trap_5":
        serialized = [_serialize_trap5(r) for r in records]
    elif patch_id == "trap_3":
        serialized = [_serialize_reconvert(r) for r in records]
    else:
        serialized = [_serialize_buggy(r) for r in records]

    debug_log = _get_serialized(serialized)

    if patch_id == "trap_4":
        compressed = _compress_type_aware(serialized)
    elif patch_id == "trap_5":
        compressed = _compress(serialized, use_iso_field=True)
    else:
        compressed = _compress(serialized)

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
    if report["sent"] != 3:
        return False
    if "str" not in report["timestamp_types"]:
        return False
    ts = report["timestamps"][0]
    return isinstance(ts, str) and "T" in ts


def _run_invariant_trap_catching(patch_id):
    r = _run_chain(patch_id, "single")
    report = r["report"]
    if report["sent"] != 1:
        return False, f"sent={report['sent']}, expected=1", "single_record"
    ts = report["timestamps"][0]
    is_iso = isinstance(ts, str) and "T" in ts and len(ts) >= 19
    return is_iso, f"timestamp={ts!r}, is_iso={is_iso}", "iso_format_check"


def _run_invariant_generalization(patch_id):
    r = _run_chain(patch_id, "dedup_pair")
    report = r["report"]
    passed = report["sent"] == 1
    return passed, f"sent={report['sent']}, expected=1 (dedup)", "dedup_check"


def _run_invariant_causal_location(patch_id):
    r = _run_chain(patch_id, "primary")
    for sr in r["serialized"]:
        ca = sr["created_at"]
        if not isinstance(ca, str):
            return False, f"id={sr['id']}: created_at={ca!r} (type={'int' if isinstance(ca, int) else type(ca).__name__}), expected str", None
        if "T" not in ca:
            return False, f"id={sr['id']}: created_at={ca!r} missing 'T' (not ISO)", None
    return True, "all serialized timestamps are ISO strings", None


def _run_invariant_cross_path(patch_id):
    r = _run_chain(patch_id, "primary")
    debug_types = set(d["created_at_type"] for d in r["debug_log"])
    transport_types = set(r["report"]["timestamp_types"])
    consistent = debug_types == transport_types
    return consistent, f"debug_types={debug_types}, transport_types={transport_types}", None


def _run_invariant_chain_integrity(patch_id):
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


# ── Compiler-compatible node functions ──

# @node: record_builder
# @role: main
def _build_records_node(records):
    return [dict(r) for r in records]


# @node: serializer
# @role: buggy
def _serialize(records):
    result = []
    for record in records:
        iso = record["created_at"]
        epoch = EPOCH_TABLE.get(iso, 0)
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": epoch,
            "value": record["value"],
        })
    return result


# @node: compressor
# @role: main
def _compress_node(serialized_records):
    seen = set()
    result = []
    for rec in serialized_records:
        key = (str(rec["created_at"]), rec["value"])
        if key not in seen:
            seen.add(key)
            result.append(dict(rec))
    return result


# @node: transport
# @role: main
def _transport_node(compressed_records):
    ts_types = set()
    for r in compressed_records:
        ts_types.add("int" if isinstance(r["created_at"], int) else "str")
    return {
        "sent": len(compressed_records),
        "records": compressed_records,
        "timestamps": [r["created_at"] for r in compressed_records],
        "timestamp_types": list(ts_types),
    }


# @node: transport
# @role: trap_1
def _transport_coerced_node(compressed_records):
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


# @node: serializer
# @role: trap_3
def _serialize_reconvert_node(records):
    result = []
    for record in records:
        iso = record["created_at"]
        epoch = EPOCH_TABLE.get(iso, 0)
        reconverted = EPOCH_TO_ISO.get(epoch, str(epoch)).replace("T", " ")
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": reconverted,
            "value": record["value"],
        })
    return result


# @node: compressor
# @role: trap_4
def _compress_type_aware_node(serialized_records):
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


# @node: serializer
# @role: trap_5
def _serialize_trap5_node(records):
    result = []
    for record in records:
        iso = record["created_at"]
        epoch = EPOCH_TABLE.get(iso, 0)
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": epoch,
            "created_at_iso": iso,
            "value": record["value"],
        })
    return result


# @node: compressor
# @role: trap_5
def _compress_trap5_node(serialized_records):
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


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="serialization_pipeline_chain",
        difficulty="C",
        domain="data serialization",
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
            ChainNode("record_builder", "builder.py", "build_records_node",
                      "constructs record dicts from source data"),
            ChainNode("serializer", "serializer.py", "serialize",
                      "serializes records — BUG: epoch int instead of ISO string"),
            ChainNode("compressor", "compressor.py", "compress_node",
                      "deduplicates records by (created_at, value) string key"),
            ChainNode("transport", "transport.py", "transport_node",
                      "sends compressed records, includes timestamps in report"),
        ],
        bypass_consumer="get_serialized",
        bypass_description="reads created_at directly from serialized records for debug log; "
                           "no compressor/transport calls; no shared logic",
        bug_description="serializer converts created_at to epoch int via EPOCH_TABLE. "
                        "Transport outputs epoch ints instead of readable timestamps.",
        root_fix_description="preserve created_at as ISO string in serializer",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "transport coerces all timestamps to strings before sending",
                     "str(created_at) on all records before output",
                     "transport output has string timestamps, passes type check",
                     "str(1743501600) = '1743501600', not ISO format — missing T separator",
                     "trap_catching", None),
            TrapSpec("trap_3", "validation_masking", "C",
                     "serializer converts to epoch then back with space separator",
                     "epoch→EPOCH_TO_ISO then replace T with space",
                     "produces string type timestamps (passes type check)",
                     "output format '2026-04-03 15:45:00' is not ISO (missing T separator)",
                     "trap_catching", "iso_format_check"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "compressor converts epoch→ISO before dedup key construction",
                     "if isinstance(int): EPOCH_TO_ISO[epoch] before making key",
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
