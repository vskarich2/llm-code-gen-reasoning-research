"""Tests for event_etl_chain.

Bug: normalizer lowercases ALL field values including user_id.
     Alice_Smith -> alice_smith, enricher lookup fails, tier=unknown.
Fix: preserve user_id case; only lowercase event_type and currency.
"""


def test(mod):
    errors = []

    normalize = getattr(mod, "normalize", None)
    enrich_node = getattr(mod, "enrich_node", None)
    write_events = getattr(mod, "write_events", None)
    if not normalize or not enrich_node or not write_events:
        return False, ["required functions not found: normalize, enrich_node, write_events"]

    RAW_EVENTS = getattr(mod, "RAW_EVENTS", None)
    if RAW_EVENTS is None:
        return False, ["RAW_EVENTS not found in module"]

    # Invariant 1: user_id case preserved after normalization
    primary = [dict(e) for e in RAW_EVENTS["primary"]]
    normalized = normalize(primary)
    if normalized[0]["user_id"] != "Alice_Smith":
        errors.append(f"invariant 1: Alice_Smith user_id={normalized[0]['user_id']!r} (case not preserved)")

    # Invariant 2: full pipeline — Alice gets premium tier
    enriched = enrich_node(normalized)
    written = write_events(enriched)
    alice = written[0]
    if alice["tier"] == "unknown":
        errors.append("invariant 2: alice tier=unknown after fix")
    elif alice["tier"] != "premium":
        errors.append(f"invariant 2: alice tier={alice['tier']!r}, expected 'premium'")

    # Invariant 3: SYSADMIN (no separator, all caps) resolves to admin tier
    sysadmin_events = [dict(e) for e in RAW_EVENTS["sysadmin"]]
    normalized_sa = normalize(sysadmin_events)
    enriched_sa = enrich_node(normalized_sa)
    written_sa = write_events(enriched_sa)
    if written_sa[0]["tier"] != "admin":
        errors.append(f"invariant 3: SYSADMIN tier={written_sa[0]['tier']!r}, expected 'admin'")

    # Invariant 4: Carol-Wu (hyphenated) resolves to premium
    carol_events = [dict(e) for e in RAW_EVENTS["hyphen_user"]]
    normalized_carol = normalize(carol_events)
    enriched_carol = enrich_node(normalized_carol)
    written_carol = write_events(enriched_carol)
    if written_carol[0]["tier"] != "premium":
        errors.append(f"invariant 4: Carol-Wu tier={written_carol[0]['tier']!r}, expected 'premium'")

    return not errors, errors
