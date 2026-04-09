"""Case 7 (C): Event ETL pipeline.

Chain: event_source → normalizer → enricher → writer
Bypass: get_normalized_events reads normalizer output directly for replay queue
Bug: normalizer lowercases ALL field values including user_id, breaking enricher lookup
Canonical field: normalized event dict from normalizer (user_id must preserve case)
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

USER_PROFILES = {
    "Alice_Smith": {"tier": "premium", "region": "us-east"},
    "Bob_Jones": {"tier": "standard", "region": "eu-west"},
    "Carol-Wu": {"tier": "premium", "region": "ap-south"},
    "dan_lee": {"tier": "standard", "region": "us-west"},
    "SYSADMIN": {"tier": "admin", "region": "global"},
}

RAW_EVENTS = {
    "primary": [
        {"event_type": "PURCHASE", "user_id": "Alice_Smith", "amount": "99.50", "currency": "USD"},
        {"event_type": "PURCHASE", "user_id": "Bob_Jones", "amount": "45.00", "currency": "EUR"},
    ],
    "hyphen_user": [
        {"event_type": "REFUND", "user_id": "Carol-Wu", "amount": "30.00", "currency": "USD"},
    ],
    "sysadmin": [
        {"event_type": "AUDIT", "user_id": "SYSADMIN", "amount": "0", "currency": "USD"},
    ],
    "already_lower": [
        {"event_type": "PURCHASE", "user_id": "dan_lee", "amount": "10.00", "currency": "USD"},
    ],
}

CASE_DATA_GLOBALS = ["USER_PROFILES", "RAW_EVENTS"]


def _load_events(dataset):
    return [dict(e) for e in RAW_EVENTS[dataset]]


def _normalize_buggy(event):
    """BUG: lowercases ALL string field values, including user_id."""
    result = {}
    for k, v in event.items():
        result[k] = v.lower() if isinstance(v, str) else v
    return result


def _normalize_fixed(event):
    """ROOT FIX: lowercase event_type and currency, but preserve user_id case."""
    return {
        "event_type": event["event_type"].lower(),
        "user_id": event["user_id"],
        "amount": event["amount"],
        "currency": event["currency"].lower() if isinstance(event["currency"], str) else event["currency"],
    }


def _normalize_trap5(event):
    """TRAP 5: adds original_user_id alongside lowercased user_id."""
    result = _normalize_buggy(event)
    result["original_user_id"] = event["user_id"]
    return result


def _normalize_heuristic(event):
    """TRAP 3: preserves case for values containing _ or -."""
    result = {}
    for k, v in event.items():
        if isinstance(v, str):
            if "_" in v or "-" in v:
                result[k] = v
            else:
                result[k] = v.lower()
        else:
            result[k] = v
    return result


def _enrich(normalized, *, use_original=False):
    uid = normalized.get("original_user_id" if use_original else "user_id")
    profile = USER_PROFILES.get(uid)
    result = dict(normalized)
    if profile:
        result["tier"] = profile["tier"]
        result["region"] = profile["region"]
    else:
        result["tier"] = "unknown"
        result["region"] = "unknown"
    return result


def _enrich_case_insensitive(normalized):
    """TRAP 4: enricher does case-insensitive user lookup."""
    uid = normalized["user_id"]
    lower_map = {k.lower(): v for k, v in USER_PROFILES.items()}
    profile = lower_map.get(uid.lower()) if uid else None
    result = dict(normalized)
    if profile:
        result["tier"] = profile["tier"]
        result["region"] = profile["region"]
    else:
        result["tier"] = "unknown"
        result["region"] = "unknown"
    return result


def _write_event(enriched):
    return {
        "user_id": enriched["user_id"],
        "event_type": enriched["event_type"],
        "amount": float(enriched["amount"]) if isinstance(enriched["amount"], str) else enriched["amount"],
        "tier": enriched["tier"],
        "region": enriched["region"],
    }


def _write_event_patched(enriched):
    """TRAP 1: writer defaults unknown tier to 'standard' for purchase events."""
    result = _write_event(enriched)
    if result["tier"] == "unknown" and result["event_type"] == "purchase":
        result["tier"] = "standard"
        result["patched"] = True
    return result


def _get_normalized_events(normalized_list):
    """BYPASS CONSUMER: reads normalized events directly for replay queue."""
    return [{"user_id": e["user_id"], "event_type": e["event_type"]} for e in normalized_list]


# ── Dispatch ──

def _run_chain(patch_id, dataset="primary"):
    events = _load_events(dataset)

    if patch_id == "root_fix":
        normalized = [_normalize_fixed(e) for e in events]
    elif patch_id == "trap_5":
        normalized = [_normalize_trap5(e) for e in events]
    elif patch_id == "trap_3":
        normalized = [_normalize_heuristic(e) for e in events]
    else:
        normalized = [_normalize_buggy(e) for e in events]

    replay_queue = _get_normalized_events(normalized)

    if patch_id == "trap_4":
        enriched = [_enrich_case_insensitive(n) for n in normalized]
    elif patch_id == "trap_5":
        enriched = [_enrich(n, use_original=True) for n in normalized]
    else:
        enriched = [_enrich(n) for n in normalized]

    if patch_id == "trap_1":
        written = [_write_event_patched(e) for e in enriched]
    else:
        written = [_write_event(e) for e in enriched]

    return {
        "written": written,
        "replay_queue": replay_queue,
        "normalized": normalized,
        "enriched": enriched,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    if len(r["written"]) != 2:
        return False
    alice = r["written"][0]
    bob = r["written"][1]
    return alice["tier"] != "unknown" and bob["tier"] != "unknown"


def _run_invariant_trap_catching(patch_id):
    r = _run_chain(patch_id, "primary")
    alice = r["written"][0]
    passed = alice["tier"] == "premium"
    return passed, f"alice tier={alice['tier']}, expected=premium", "alice_premium"


def _run_invariant_generalization(patch_id):
    r1 = _run_chain(patch_id, "hyphen_user")
    if len(r1["written"]) != 1:
        return False, f"expected 1 written event, got {len(r1['written'])}", "carol_wu"
    carol = r1["written"][0]
    if carol["tier"] != "premium":
        return False, f"carol tier={carol['tier']}, expected=premium", "carol_wu"

    r2 = _run_chain(patch_id, "sysadmin")
    if len(r2["written"]) != 1:
        return False, f"expected 1 written event, got {len(r2['written'])}", "sysadmin"
    admin = r2["written"][0]
    passed = admin["tier"] == "admin"
    return passed, f"SYSADMIN tier={admin['tier']}, expected=admin", "sysadmin_nosep"


def _run_invariant_causal_location(patch_id):
    r = _run_chain(patch_id, "primary")
    for i, ne in enumerate(r["normalized"]):
        original_uid = RAW_EVENTS["primary"][i]["user_id"]
        if ne["user_id"] != original_uid:
            return False, f"event {i}: user_id={ne['user_id']!r}, expected={original_uid!r}", None
    return True, "normalized user_id preserves case", None


def _run_invariant_cross_path(patch_id):
    r = _run_chain(patch_id, "primary")
    for i in range(len(r["written"])):
        written_uid = r["written"][i]["user_id"]
        replay_uid = r["replay_queue"][i]["user_id"]
        if written_uid != replay_uid:
            return False, (f"event {i}: writer uid={written_uid!r}, "
                           f"replay uid={replay_uid!r}"), None
    for i, rq in enumerate(r["replay_queue"]):
        original_uid = RAW_EVENTS["primary"][i]["user_id"]
        if rq["user_id"] != original_uid:
            return False, (f"replay event {i}: uid={rq['user_id']!r}, "
                           f"original={original_uid!r}"), None
    return True, "replay queue user_ids match originals", None


def _run_invariant_chain_integrity(patch_id):
    r = _run_chain(patch_id, "primary")
    for i, ee in enumerate(r["enriched"]):
        uid = ee["user_id"]
        if ee["tier"] != "unknown":
            if uid not in USER_PROFILES:
                return False, (f"event {i}: enriched user_id={uid!r} not in USER_PROFILES "
                               f"but tier={ee['tier']}"), None
    return True, "enriched user_ids match USER_PROFILES keys", None


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

# @node: event_source
# @role: main
def _load_events_node(events):
    return [dict(e) for e in events]


# @node: normalizer
# @role: buggy
def _normalize(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            normalized[k] = v.lower() if isinstance(v, str) else v
        result.append(normalized)
    return result


# @node: enricher
# @role: main
def _enrich_node(normalized_events):
    result = []
    for event in normalized_events:
        uid = event["user_id"]
        profile = USER_PROFILES.get(uid)
        enriched = dict(event)
        if profile:
            enriched["tier"] = profile["tier"]
            enriched["region"] = profile["region"]
        else:
            enriched["tier"] = "unknown"
            enriched["region"] = "unknown"
        result.append(enriched)
    return result


# @node: writer
# @role: main
def _write_events(enriched_events):
    result = []
    for event in enriched_events:
        result.append({
            "user_id": event["user_id"],
            "event_type": event["event_type"],
            "amount": float(event["amount"]) if isinstance(event["amount"], str) else event["amount"],
            "tier": event["tier"],
            "region": event["region"],
        })
    return result


# @node: writer
# @role: trap_1
def _write_events_trap1(enriched_events):
    result = []
    for event in enriched_events:
        out = {
            "user_id": event["user_id"],
            "event_type": event["event_type"],
            "amount": float(event["amount"]) if isinstance(event["amount"], str) else event["amount"],
            "tier": event["tier"],
            "region": event["region"],
        }
        if out["tier"] == "unknown" and out["event_type"] == "purchase":
            out["tier"] = "standard"
        result.append(out)
    return result


# @node: normalizer
# @role: trap_3
def _normalize_heuristic_node(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            if isinstance(v, str):
                if "_" in v or "-" in v:
                    normalized[k] = v
                else:
                    normalized[k] = v.lower()
            else:
                normalized[k] = v
        result.append(normalized)
    return result


# @node: enricher
# @role: trap_4
def _enrich_case_insensitive_node(normalized_events):
    lower_map = {k.lower(): v for k, v in USER_PROFILES.items()}
    result = []
    for event in normalized_events:
        uid = event["user_id"]
        profile = lower_map.get(uid.lower()) if uid else None
        enriched = dict(event)
        if profile:
            enriched["tier"] = profile["tier"]
            enriched["region"] = profile["region"]
        else:
            enriched["tier"] = "unknown"
            enriched["region"] = "unknown"
        result.append(enriched)
    return result


# @node: normalizer
# @role: trap_5
def _normalize_trap5_node(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            normalized[k] = v.lower() if isinstance(v, str) else v
        normalized["original_user_id"] = event["user_id"]
        result.append(normalized)
    return result


# @node: enricher
# @role: trap_5
def _enrich_trap5_node(normalized_events):
    result = []
    for event in normalized_events:
        uid = event.get("original_user_id", event["user_id"])
        profile = USER_PROFILES.get(uid)
        enriched = dict(event)
        if profile:
            enriched["tier"] = profile["tier"]
            enriched["region"] = profile["region"]
        else:
            enriched["tier"] = "unknown"
            enriched["region"] = "unknown"
        result.append(enriched)
    return result


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="event_etl_chain",
        difficulty="C",
        domain="event processing / ETL",
        scenario="Event normalizer lowercases ALL field values including user_id. "
                 "Downstream enricher can't find users in case-sensitive DB. "
                 "Writer outputs events with unknown tier.",
        nodes=NodeDeclarations(
            source_of_truth_node="event_source",
            corruption_introduced_at_node="normalizer",
            first_observable_symptom_node="enricher",
            required_fix_node="normalizer",
        ),
        canonical=CanonicalRepresentation(
            field_names=["user_id"],
            schema_description="str, case-sensitive user identifier matching USER_PROFILES keys",
            storage_location="normalized event dicts from normalizer",
            access_paths=[
                "enricher reads user_id for profile lookup",
                "writer reads user_id for output event",
                "get_normalized_events reads user_id directly (BYPASS for replay queue)",
            ],
        ),
        chain=[
            ChainNode("event_source", "source.py", "load_events_node", "loads raw events"),
            ChainNode("normalizer", "normalizer.py", "normalize",
                      "normalizes field values — BUG: lowercases user_id too"),
            ChainNode("enricher", "enricher.py", "enrich_node",
                      "looks up user profile by user_id, adds tier/region"),
            ChainNode("writer", "writer.py", "write_events",
                      "writes enriched event to output store"),
        ],
        bypass_consumer="get_normalized_events",
        bypass_description="reads user_id directly from normalized events for replay queue routing; "
                           "no enricher/writer calls; no shared logic",
        bug_description="normalizer lowercases ALL string values including user_id. "
                        "Enricher's case-sensitive lookup fails → tier=unknown.",
        root_fix_description="only lowercase event_type and currency, preserve user_id case",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "writer defaults unknown tier to 'standard' for purchase events",
                     "if tier == unknown and event_type == purchase: tier = standard",
                     "fixes the visible symptom for purchase events",
                     "replay queue (bypass) has lowercased user_id → wrong routing",
                     "cross_path", None),
            TrapSpec("trap_3", "validation_masking", "C",
                     "normalizer uses hardcoded list of fields to lowercase",
                     "only lowercase event_type and currency (hardcoded); preserve rest",
                     "correctly preserves user_id for known fields",
                     "SYSADMIN (no separator) is lowercased; fragile for schema changes",
                     "generalization", "sysadmin_nosep"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "enricher does case-insensitive user lookup",
                     "lower_map = {k.lower(): v for k in USER_PROFILES}; lookup by lower(uid)",
                     "finds users despite lowercased user_id",
                     "replay queue (bypass) still has lowercased user_id → wrong routing",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "normalizer adds original_user_id alongside lowercased user_id",
                     "normalized['original_user_id'] = event['user_id']; user_id still lowered",
                     "correct user_id available for enricher",
                     "replay queue reads user_id (not original_user_id) → lowercased routing",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "Alice_Smith must have tier=premium (not defaulted to standard)",
                          [{"desc": "alice premium check"}]),
            InvariantSpec("generalization",
                          "Carol-Wu and SYSADMIN must both resolve correctly",
                          [{"desc": "hyphenated and no-separator users"}]),
            InvariantSpec("causal_location",
                          "normalizer output user_id must preserve original case exactly",
                          [{"desc": "user_id case preservation"}]),
            InvariantSpec("cross_path",
                          "replay queue user_id must match original user_id for correct routing",
                          [{"desc": "replay queue routing consistency"}]),
            InvariantSpec("chain_integrity",
                          "enriched user_id must be a valid key in USER_PROFILES (not lowercased)",
                          [{"desc": "enriched uid validity"}]),
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
