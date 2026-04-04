"""Case 7 (C): Event ETL pipeline.

Chain: event_source → normalizer → enricher → writer
Bypass: get_normalized_events reads normalizer output directly for replay queue
Bug: normalizer lowercases ALL field values including user_id, breaking enricher lookup
Canonical field: normalized event dict from normalizer (user_id must preserve case)
"""

from data.deep_dependency_chain.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

USER_PROFILES = {
    "Alice_Smith": {"tier": "premium", "region": "us-east"},
    "Bob_Jones": {"tier": "standard", "region": "eu-west"},
    "Carol-Wu": {"tier": "premium", "region": "ap-south"},
    "dan_lee": {"tier": "standard", "region": "us-west"},  # already lowercase
    "SYSADMIN": {"tier": "admin", "region": "global"},  # all caps, no separator
}

RAW_EVENTS = {
    "primary": [
        {"event_type": "PURCHASE", "user_id": "Alice_Smith", "amount": "99.50", "currency": "USD"},
        {"event_type": "PURCHASE", "user_id": "Bob_Jones", "amount": "45.00", "currency": "EUR"},
    ],
    "alternate_hyphen": [
        {"event_type": "REFUND", "user_id": "Carol-Wu", "amount": "30.00", "currency": "USD"},
    ],
    "alternate_nosep": [
        {"event_type": "AUDIT", "user_id": "SYSADMIN", "amount": "0", "currency": "USD"},
    ],
    "trap_catching_input": [
        {"event_type": "PURCHASE", "user_id": "dan_lee", "amount": "10.00", "currency": "USD"},
    ],
}


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
        "user_id": event["user_id"],  # preserve case
        "amount": event["amount"],
        "currency": event["currency"].lower() if isinstance(event["currency"], str) else event["currency"],
    }


def _normalize_trap5(event):
    """TRAP 5: adds original_user_id alongside lowercased user_id."""
    result = _normalize_buggy(event)
    result["original_user_id"] = event["user_id"]
    return result


def _normalize_heuristic(event):
    """TRAP 3: preserves case for values containing _ or - (looks like an ID).
    Lowercases everything else. Works for Alice_Smith, Bob_Jones, Carol-Wu.
    Fails for SYSADMIN (no separator → lowercased → sysadmin → not found)."""
    result = {}
    for k, v in event.items():
        if isinstance(v, str):
            if "_" in v or "-" in v:
                result[k] = v  # preserve — looks like compound ID
            else:
                result[k] = v.lower()  # lowercase — looks like regular text
        else:
            result[k] = v
    return result


def _enrich(normalized, *, use_original=False):
    """Look up user profile and add tier/region."""
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
    # Build lowercase lookup map
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
    """Write enriched event to output store."""
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
    """BYPASS CONSUMER: reads normalized events directly for replay queue.
    Replay queue needs exact user_id to route events."""
    return [{"user_id": e["user_id"], "event_type": e["event_type"]} for e in normalized_list]


# ── Dispatch ──

def _run_chain(patch_id, dataset="primary"):
    events = _load_events(dataset)

    # Step A: normalize
    if patch_id == "root_fix":
        normalized = [_normalize_fixed(e) for e in events]
    elif patch_id == "trap_5":
        normalized = [_normalize_trap5(e) for e in events]
    elif patch_id == "trap_3":
        normalized = [_normalize_heuristic(e) for e in events]
    else:
        normalized = [_normalize_buggy(e) for e in events]

    # Bypass
    replay_queue = _get_normalized_events(normalized)

    # Step B: enrich
    if patch_id == "trap_4":
        enriched = [_enrich_case_insensitive(n) for n in normalized]
    elif patch_id == "trap_5":
        enriched = [_enrich(n, use_original=True) for n in normalized]
    else:
        enriched = [_enrich(n) for n in normalized]

    # Step C: write
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
    # Primary symptom: events written with tier=unknown. Fix must resolve tiers.
    if len(r["written"]) != 2:
        return False
    alice = r["written"][0]
    bob = r["written"][1]
    return alice["tier"] != "unknown" and bob["tier"] != "unknown"


def _run_invariant_trap_catching(patch_id):
    """dan_lee is already lowercase in USER_PROFILES. Normalizer lowercasing
    doesn't break his lookup. But trap_1 defaults unknown→standard for purchases.
    Since dan_lee IS found (tier=standard), trap_1 doesn't trigger.

    Need a case where trap_1's defaulting is wrong. Use dan_lee but check
    that his tier comes from the DB, not from the default.

    Actually: with buggy normalizer, dan_lee → dan_lee (already lower) → found → standard. Correct!
    With trap_1 on dan_lee: tier=standard (from DB, not patched). Correct!
    Trap_catching needs to catch trap_1 specifically.

    Better: use an event_type that's NOT 'purchase'. Trap_1 only defaults for purchase events.
    If a PURCHASE event from an unknown user gets defaulted to standard, that's the trap.
    But we need a user who SHOULD be unknown but trap_1 makes standard.

    Use a non-existent user with a purchase event. The correct output is tier=unknown.
    Trap_1 defaults to standard → WRONG."""
    r = _run_chain(patch_id, "trap_catching_input")
    # dan_lee exists in DB as standard. All normalizers find him.
    # This won't catch trap_1. Need different approach.
    #
    # Actually: with BUGGY normalizer on Alice_Smith → alice_smith → not found → unknown.
    # Trap_1: unknown + purchase → default standard. So Alice becomes standard.
    # But Alice should be premium. Primary test catches this.
    # For trap_catching, I need a NON-purchase event where trap_1 doesn't activate,
    # but the user is still broken.
    # Hmm, trap_catching should test that trap_1's default incorrectly promotes someone.
    #
    # Simplest: keep dan_lee test. dan_lee is found correctly (standard).
    # Trap_1 doesn't trigger (tier != unknown). So trap_catching PASSES for trap_1.
    # For buggy: dan_lee found (standard) → PASSES.
    # For trap_3: dan_lee found (standard) → PASSES.
    # Trap_catching only fails for patches that break dan_lee's lookup.
    # No patch breaks dan_lee (he's already lowercase).
    # So trap_catching passes for everything.
    #
    # I need a trap_catching input where trap_1 specifically fails.
    # Use primary case_data but check Alice's tier is NOT "standard".
    # Wait, that's the primary test.
    #
    # Let me redesign trap_catching: use a dataset with a user who should be
    # unknown and a NON-purchase event. trap_1 only defaults purchases.
    # With a non-purchase event, trap_1 leaves tier as unknown (correct).
    # trap_catching passes. But I need it to FAIL for trap_1.
    #
    # Reverse: use a PURCHASE event from an unknown user.
    # Correct: tier=unknown. Trap_1: unknown+purchase → standard. WRONG.
    # But ALL buggy patches produce unknown for this user (since no user in DB matches).
    # So trap_catching would fail for ALL non-root patches that don't fix the lookup.
    # That makes trap_catching fail broadly, not specifically for trap_1.
    #
    # Actually that's fine — trap_catching is designed to catch endpoint compensation.
    # If other traps also fail trap_catching, cross_path (higher precedence) catches them first.
    #
    # Let me add an unknown user to the trap_catching dataset.
    pass

    # Use primary dataset, check Alice is premium (not defaulted to standard)
    r = _run_chain(patch_id, "primary")
    alice = r["written"][0]
    # Alice should be premium, not standard
    passed = alice["tier"] == "premium"
    return passed, f"alice tier={alice['tier']}, expected=premium", "alice_premium"


def _run_invariant_generalization(patch_id):
    """Carol-Wu has a hyphen in user_id. Trap_3 (selective lowercase) preserves
    user_id case → Carol-Wu found → premium. But trap_4 (case-insensitive lookup)
    also finds her. Need something trap_3 gets wrong.

    trap_3 uses hardcoded LOWERCASE_FIELDS = {event_type, currency}. It does NOT
    lowercase user_id → Carol-Wu preserved. But what about 'amount'? Amount is
    not in LOWERCASE_FIELDS → preserved as string "30.00". That's correct (writer
    handles string→float conversion).

    Actually trap_3 CORRECTLY handles everything because it doesn't lowercase user_id.
    trap_3 only fails if a new field needs lowercasing that's not in the hardcoded list.

    I don't have such a field in current schema. Let me check what trap_3 actually
    fails on...

    With trap_3 on primary:
    - normalized: event_type="purchase", user_id="Alice_Smith", amount="99.50", currency="usd"
    - enricher: Alice_Smith found → premium ✓
    - writer: tier=premium ✓

    trap_3 passes everything! Because the selective lowercase list happens to be correct.
    The trap_3 is supposed to be a validation mask that's too narrow, but it works here.

    Fix: make the generalization test check that event_type is lowercased.
    trap_3 lowercases event_type → "purchase". That's correct.

    Hmm, trap_3 actually produces correct output for all cases.
    It's only wrong in principle (hardcoded list is fragile) not in practice.

    I need trap_3 to actually fail on something. Let me add a field that should
    be lowercased but isn't in the hardcoded list.

    Add "category" field to events that should be lowercased for matching.
    But that changes the event schema significantly.

    Simpler: make the generalization check that the normalizer output's user_id
    is EXACTLY the original (not lowercased). For trap_3 this passes. For trap_4
    (case-insensitive enricher with buggy normalizer), user_id is lowercased but
    enricher finds user anyway.

    Actually: the generalization invariant should test something specific to
    trap_3's failure mode. If trap_3 doesn't actually fail... I need to redesign it.

    Redesign trap_3: normalizer lowercases only fields with ALL-CAPS values.
    event_type "PURCHASE" → all caps → lowercased to "purchase". ✓
    user_id "Alice_Smith" → mixed case → NOT lowercased. ✓
    currency "USD" → all caps → lowercased to "usd". ✓

    But what about user_id "SYSTEM_BOT"? All caps → lowercased to "system_bot".
    If SYSTEM_BOT is in the DB, the lowercased version won't match.

    I can add this to the generalization test!
    """
    # Test 1: Carol-Wu (hyphenated) should resolve
    r1 = _run_chain(patch_id, "alternate_hyphen")
    if len(r1["written"]) != 1:
        return False, f"expected 1 written event, got {len(r1['written'])}", "carol_wu"
    carol = r1["written"][0]
    if carol["tier"] != "premium":
        return False, f"carol tier={carol['tier']}, expected=premium", "carol_wu"

    # Test 2: SYSADMIN (no separator) must resolve to admin tier
    # Trap_3 heuristic lowercases values without _ or - → "sysadmin" → not found
    r2 = _run_chain(patch_id, "alternate_nosep")
    if len(r2["written"]) != 1:
        return False, f"expected 1 written event, got {len(r2['written'])}", "sysadmin"
    admin = r2["written"][0]
    passed = admin["tier"] == "admin"
    return passed, f"SYSADMIN tier={admin['tier']}, expected=admin", "sysadmin_nosep"


def _run_invariant_causal_location(patch_id):
    """Normalizer output user_id must preserve original case."""
    r = _run_chain(patch_id, "primary")
    for i, ne in enumerate(r["normalized"]):
        original_uid = RAW_EVENTS["primary"][i]["user_id"]
        if ne["user_id"] != original_uid:
            return False, f"event {i}: user_id={ne['user_id']!r}, expected={original_uid!r}", None
    return True, "normalized user_id preserves case", None


def _run_invariant_cross_path(patch_id):
    """Replay queue (bypass) user_id must match writer's user_id.
    If enricher fixes lookup but normalizer still lowercased user_id,
    replay queue routes to wrong user."""
    r = _run_chain(patch_id, "primary")
    for i in range(len(r["written"])):
        written_uid = r["written"][i]["user_id"]
        replay_uid = r["replay_queue"][i]["user_id"]
        if written_uid != replay_uid:
            # Check if they represent the same user but with different case
            if written_uid.lower() == replay_uid.lower():
                return False, (f"event {i}: writer uid={written_uid!r}, "
                               f"replay uid={replay_uid!r} (case mismatch)"), None
            return False, (f"event {i}: writer uid={written_uid!r}, "
                           f"replay uid={replay_uid!r} (different users)"), None
    # Also: replay user_id must match ORIGINAL user_id for correct routing
    for i, rq in enumerate(r["replay_queue"]):
        original_uid = RAW_EVENTS["primary"][i]["user_id"]
        if rq["user_id"] != original_uid:
            return False, (f"replay event {i}: uid={rq['user_id']!r}, "
                           f"original={original_uid!r}"), None
    return True, "replay queue user_ids match originals", None


def _run_invariant_chain_integrity(patch_id):
    """Enriched tier must come from the correct user profile lookup.
    If normalizer lowercases but enricher does case-insensitive lookup,
    the enriched user_id won't match the DB key exactly."""
    r = _run_chain(patch_id, "primary")
    for i, ee in enumerate(r["enriched"]):
        uid = ee["user_id"]
        # The enriched event's user_id must be a key in USER_PROFILES
        # (or be unknown). If user_id is lowercased, it won't be a valid key.
        if ee["tier"] != "unknown":
            # User was found — verify user_id is a valid DB key
            if uid not in USER_PROFILES:
                return False, (f"event {i}: enriched user_id={uid!r} not in USER_PROFILES "
                               f"but tier={ee['tier']} (lookup used different key)"), None
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
            ChainNode("event_source", "source.py", "load_events", "loads raw events"),
            ChainNode("normalizer", "normalizer.py", "normalize",
                      "normalizes field values — BUG: lowercases user_id too"),
            ChainNode("enricher", "enricher.py", "enrich",
                      "looks up user profile by user_id, adds tier/region"),
            ChainNode("writer", "writer.py", "write_event",
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
                     "Carol-Wu (hyphenated name) should still work; but the hardcoded "
                     "approach is fragile for schema changes",
                     "generalization", "carol_wu"),
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
                          "Carol-Wu (hyphenated name) must resolve to premium/ap-south",
                          [{"desc": "hyphenated user_id"}]),
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
