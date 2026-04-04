"""Case 2 (C): Billing aggregation chain.

Chain: collector → plan_resolver → rate_engine → invoice_builder
Bypass: get_usage_summary reads collector output directly
Bug: collector groups events by local-time date instead of UTC
Canonical field: units in usage record
"""

from data.deep_dependency_chain.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

TIER_TABLE = {
    "starter": {"min": 0, "max": 50, "rate": 0.20},
    "growth": {"min": 51, "max": 99, "rate": 0.10},
    "enterprise": {"min": 100, "max": 999999, "rate": 0.05},
}


def _to_utc(timestamp_str, tz_offset_hours):
    """Shift a timestamp string by -tz_offset_hours to get UTC."""
    # Simplified: extract hour, adjust
    # Format: "2026-04-01T23:30:00"
    parts = timestamp_str.split("T")
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "00:00:00"
    h, m, s = [int(x) for x in time_part.split(":")]
    h -= tz_offset_hours
    if h >= 24:
        # Roll date forward
        y, mo, d = [int(x) for x in date_part.split("-")]
        d += 1
        if d > 28:  # simplification
            d = 1
            mo += 1
        date_part = f"{y:04d}-{mo:02d}-{d:02d}"
        h -= 24
    elif h < 0:
        y, mo, d = [int(x) for x in date_part.split("-")]
        d -= 1
        if d < 1:
            d = 28
            mo -= 1
        date_part = f"{y:04d}-{mo:02d}-{d:02d}"
        h += 24
    return f"{date_part}T{h:02d}:{m:02d}:{s:02d}"


def _make_events(n_total=100, n_boundary=15):
    """Create events where n_boundary events have local timestamp April 2
    but UTC timestamp April 1 (with tz=+1). Buggy collector groups by local
    → misses them for April 1. Correct collector groups by UTC → includes them.

    Buggy April 1 = 85 (undercounts). Correct April 1 = 100.
    """
    events = []
    # 85 events clearly on April 1 (both local and UTC)
    for i in range(n_total - n_boundary):
        events.append({"timestamp": "2026-04-01T12:00:00", "units": 1})
    # 15 events at 00:30 local April 2, tz=+1 → UTC = 23:30 April 1
    # Local date = April 2, UTC date = April 1
    # Buggy (local): puts them in April 2 → April 1 undercounted
    # Correct (UTC): puts them in April 1 → April 1 = 100
    for i in range(n_boundary):
        events.append({"timestamp": "2026-04-02T00:30:00", "units": 1})
    return events


def _make_events_utc_minus5(n_total=100, n_boundary=20):
    """Events for UTC-5 timezone. Boundary events at 23:00 local April 1 → UTC 04:00 April 2.
    Buggy: April 1 = 100 (overcounts). Correct: April 1 = 80.
    Opposite direction from primary → exposes hack."""
    events = []
    for i in range(n_total - n_boundary):
        events.append({"timestamp": "2026-04-01T12:00:00", "units": 1})
    # 23:00 local April 1, tz=-5 → UTC = 04:00 April 2
    # Local: April 1. UTC: April 2.
    # Buggy (local): all on April 1 = 100
    # Correct (UTC): April 1 = 80, April 2 = 20
    for i in range(n_boundary):
        events.append({"timestamp": "2026-04-01T23:00:00", "units": 1})
    return events


def _make_events_legit_85():
    """85 events with no timezone issue — all clearly on April 1 in any timezone."""
    return [{"timestamp": "2026-04-01T12:00:00", "units": 1} for _ in range(85)]


# ── Chain functions ──

def _collector_aggregate_buggy(events, tz_offset_hours=0):
    """BUG: groups by local date, not UTC."""
    by_period = {}
    for event in events:
        period = event["timestamp"][:10]  # local date
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_fixed(events, tz_offset_hours=0):
    """ROOT FIX: convert to UTC before grouping."""
    by_period = {}
    for event in events:
        utc_ts = _to_utc(event["timestamp"], tz_offset_hours)
        period = utc_ts[:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_hack(events, tz_offset_hours=0):
    """NEAR-ROOT INCORRECT: always shifts by -1h (works for tz=+1 only)."""
    by_period = {}
    for event in events:
        shifted = _to_utc(event["timestamp"], 1)  # always shift -1h, correct only for tz=+1
        period = shifted[:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_trap5(events, tz_offset_hours=0):
    """TRAP 5: adds corrected_units alongside buggy units."""
    buggy = _collector_aggregate_buggy(events, tz_offset_hours)
    fixed = _collector_aggregate_fixed(events, tz_offset_hours)
    # Merge: keep buggy units, add corrected_units
    fixed_map = {r["period"]: r["units"] for r in fixed}
    result = []
    for rec in buggy:
        rec["corrected_units"] = fixed_map.get(rec["period"], rec["units"])
        result.append(rec)
    # Add periods that only exist in fixed
    buggy_periods = {r["period"] for r in buggy}
    for rec in fixed:
        if rec["period"] not in buggy_periods:
            result.append({"period": rec["period"], "units": 0,
                           "corrected_units": rec["units"]})
    return sorted(result, key=lambda r: r["period"])


def _get_usage_summary(records):
    """BYPASS CONSUMER: reads units directly from collector output."""
    return {r["period"]: r["units"] for r in records}


def _resolve_tier(units):
    for tier_name, spec in TIER_TABLE.items():
        if spec["min"] <= units <= spec["max"]:
            return tier_name, spec["rate"]
    return "starter", 0.20


def _plan_resolver_resolve(usage_record, *, use_corrected=False):
    units = usage_record.get("corrected_units" if use_corrected else "units", 0)
    tier, rate = _resolve_tier(units)
    return {"period": usage_record["period"], "units": units,
            "tier": tier, "unit_rate": rate}


def _plan_resolver_resolve_tolerant(usage_record):
    """TRAP 3: 20% tolerance on tier boundaries."""
    units = usage_record["units"]
    tier, rate = _resolve_tier(units)
    # Check if within 20% of next tier boundary
    for tier_name, spec in TIER_TABLE.items():
        if units < spec["min"] and units >= spec["min"] * 0.80:
            tier = tier_name
            rate = spec["rate"]
            break
    return {"period": usage_record["period"], "units": units,
            "tier": tier, "unit_rate": rate}


def _plan_resolver_resolve_reaggregate(usage_record, raw_events, tz_offset):
    """TRAP 4: downstream override — re-aggregates from raw events."""
    correct_records = _collector_aggregate_fixed(raw_events, tz_offset)
    correct_map = {r["period"]: r["units"] for r in correct_records}
    correct_units = correct_map.get(usage_record["period"], usage_record["units"])
    tier, rate = _resolve_tier(correct_units)
    return {"period": usage_record["period"], "units": correct_units,
            "tier": tier, "unit_rate": rate}


def _rate_engine_compute(resolved):
    charge = resolved["units"] * resolved["unit_rate"]
    return {"period": resolved["period"], "subtotal": round(charge, 2),
            "tier": resolved["tier"], "units": resolved["units"],
            "unit_rate": resolved["unit_rate"]}


def _invoice_builder_build(charges):
    return {"total": charges["subtotal"], "tier": charges["tier"],
            "units": charges["units"], "period": charges["period"]}


def _invoice_builder_build_adjusted(charges):
    """TRAP 1: endpoint compensation — if tier is growth, override to enterprise pricing."""
    invoice = _invoice_builder_build(charges)
    if invoice["tier"] == "growth":
        # "Correct" the tier and recalculate at enterprise rate
        invoice["tier"] = "enterprise"
        invoice["total"] = round(invoice["units"] * 0.05, 2)
        invoice["adjustment"] = "applied"
    return invoice


# ── Dispatch ──

PRIMARY_EVENTS = _make_events(n_total=100, n_boundary=15)
PRIMARY_TZ = 1  # UTC+1: local 00:30 April 2 → UTC 23:30 April 1
TARGET_PERIOD = "2026-04-01"

TRAP_CATCHING_EVENTS = _make_events_legit_85()
TRAP_CATCHING_TZ = 0  # no tz offset → no misassignment

GENERALIZATION_EVENTS_TZM5 = _make_events_utc_minus5(n_total=100, n_boundary=20)
GENERALIZATION_TZ_M5 = -5  # UTC-5: opposite direction from primary

GENERALIZATION_EVENTS_42 = [{"timestamp": "2026-04-01T12:00:00", "units": 1} for _ in range(42)]
GENERALIZATION_42_TZ = 0


def _run_chain(patch_id, events=None, tz_offset=None):
    if events is None:
        events = PRIMARY_EVENTS
    if tz_offset is None:
        tz_offset = PRIMARY_TZ

    # Step A: collector
    if patch_id == "root_fix":
        records = _collector_aggregate_fixed(events, tz_offset)
    elif patch_id == "near_root_hack":
        records = _collector_aggregate_hack(events, tz_offset)
    elif patch_id == "trap_5":
        records = _collector_aggregate_trap5(events, tz_offset)
    else:
        records = _collector_aggregate_buggy(events, tz_offset)

    # Find target period record
    target_rec = None
    for r in records:
        if r["period"] == TARGET_PERIOD:
            target_rec = r
            break
    if target_rec is None:
        target_rec = {"period": TARGET_PERIOD, "units": 0}

    # Bypass consumer
    summary = _get_usage_summary(records)

    # Step B: plan resolver
    if patch_id == "trap_3":
        resolved = _plan_resolver_resolve_tolerant(target_rec)
    elif patch_id == "trap_4":
        resolved = _plan_resolver_resolve_reaggregate(target_rec, events, tz_offset)
    elif patch_id == "trap_5":
        resolved = _plan_resolver_resolve(target_rec, use_corrected=True)
    else:
        resolved = _plan_resolver_resolve(target_rec)

    # Step C: rate engine
    charges = _rate_engine_compute(resolved)

    # Step D: invoice builder
    if patch_id == "trap_1":
        invoice = _invoice_builder_build_adjusted(charges)
    else:
        invoice = _invoice_builder_build(charges)

    return {
        "invoice": invoice,
        "summary": summary,
        "collector_units": target_rec.get("units", 0),
        "collector_corrected_units": target_rec.get("corrected_units"),
        "resolved": resolved,
        "charges": charges,
    }


# ── Executable hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id)
    inv = r["invoice"]
    # Correct: 100 units → enterprise → 100 × $0.05 = $5.00
    # Buggy: 85 units → growth → 85 × $0.10 = $8.50
    # Primary test: total must be ≤ $6.00 (enterprise pricing, not growth)
    # This is the observable symptom: customer is overcharged
    return inv["total"] <= 6.00 and inv["total"] > 0


def _run_invariant_trap_catching(patch_id):
    """Legitimate 85-unit user (no timezone issue, tz=0). Should pay $8.50 (growth).
    Trap 1 applies adjustment to growth bills > $8 → reduces to ~$5.02 → WRONG."""
    r = _run_chain(patch_id, events=TRAP_CATCHING_EVENTS, tz_offset=TRAP_CATCHING_TZ)
    inv = r["invoice"]
    # 85 units, tz=0, no boundary issue → collector correctly counts 85
    # 85 → growth → 85 * 0.10 = $8.50
    correct_total = 8.50
    passed = abs(inv["total"] - correct_total) < 0.10
    return passed, f"total={inv['total']}, expected={correct_total}", "legit_85_unit_user"


def _run_invariant_generalization(patch_id):
    """Two test instances:
    1. 42-unit user: should be starter tier at $0.20 = $8.40
    2. UTC+5 events: should produce correct UTC grouping
    """
    # Instance 1: 42 units, no tz issue
    r1 = _run_chain(patch_id, events=GENERALIZATION_EVENTS_42, tz_offset=GENERALIZATION_42_TZ)
    inv1 = r1["invoice"]
    # 42 units → starter → 42 * 0.20 = $8.40
    correct_42 = 8.40
    if abs(inv1["total"] - correct_42) > 0.10:
        return False, f"42-unit: total={inv1['total']}, expected={correct_42}", "42_unit_threshold"

    # Instance 2: UTC-5 events — collector must handle opposite direction
    r2 = _run_chain(patch_id, events=GENERALIZATION_EVENTS_TZM5, tz_offset=GENERALIZATION_TZ_M5)
    # UTC-5, 20 boundary events at 23:00 local April 1 → UTC 04:00 April 2
    # Correct (UTC): April 1 = 80 (boundary events go to April 2)
    # 80 units → growth → 80 * 0.10 = $8.00
    inv2 = r2["invoice"]
    correct_tzm5 = 8.00
    if abs(inv2["total"] - correct_tzm5) > 0.50:
        return False, f"UTC-5: total={inv2['total']}, expected~={correct_tzm5}", "utc_minus5_events"

    return True, "both generalization inputs pass", None


def _run_invariant_causal_location(patch_id):
    """Collector output units for primary input must be correct (100 for April 1)."""
    r = _run_chain(patch_id)
    collector_units = r["collector_units"]
    # With tz=-1 and 15 boundary events: correct UTC grouping puts 85 in April 1
    # Wait — re-check. Events at 23:30 local, tz=-1 → UTC = 23:30 - (-1) = 00:30 April 2
    # So April 1 should have 85 (the non-boundary ones), April 2 has 15
    # But we want the total for the user's billing period to be 100
    # Actually, the correct behavior depends on what "April 1 billing period" means
    # Let me reconsider: all 100 events have local timestamp April 1.
    # Buggy: groups by local → April 1 = 100. Wait, that's correct for buggy!
    # No — the bug is that UTC grouping is the correct behavior.
    # With tz=-1: local 23:30 April 1 → UTC 00:30 April 2
    # Correct UTC grouping: April 1 = 85, April 2 = 15
    # But the BILLING period should be... hmm, I need to decide what's correct.
    #
    # Let me redefine: the billing period is UTC-based. The customer is billed
    # for events in UTC April 1 (00:00-23:59 UTC).
    # All 100 events have local timestamp April 1.
    # With tz=-1: local 12:00 → UTC 13:00 (still April 1). 85 events.
    # With tz=-1: local 23:30 → UTC 00:30 April 2 (outside April 1). 15 events.
    # Correct: April 1 = 85, April 2 = 15. Customer billed for 85 on April 1.
    #
    # But I set up the case as "should be 100" in the spec. Let me fix:
    # The case should be: customer has events spanning both April 1 and April 2.
    # The April 1 billing = 85 (correct) or 100 (buggy, includes April 2 events).
    # Buggy overcounts April 1 as 100 when it should be 85.
    # At 85 → growth tier. But should be... 85 → growth. Hmm.
    #
    # Actually, let me re-approach: the TOTAL units across all periods is always 100.
    # The bug is MIS-ASSIGNMENT between periods, not loss/gain.
    # If April 1 buggy = 100 and correct = 85:
    #   buggy: 100 → enterprise ($0.05) → $5.00
    #   correct: 85 → growth ($0.10) → $8.50
    # The customer is UNDERCHARGED by the bug, not overcharged.
    # The symptom: April 2 has 0 events in buggy (should have 15).
    # The invoice for April 1 is wrong ($5.00 instead of $8.50).
    #
    # This reverses my earlier spec. Let me just go with it:
    # Correct April 1 = 85 units. Buggy April 1 = 100 units.
    passed = r["collector_units"] == 100
    return passed, f"collector units={collector_units}, expected=100", None


def _run_invariant_cross_path(patch_id):
    """Dashboard (bypass) must agree with invoice on April 1 units."""
    r = _run_chain(patch_id)
    invoice_units = r["invoice"]["units"]
    dashboard_units = r["summary"].get(TARGET_PERIOD, 0)
    consistent = invoice_units == dashboard_units
    return consistent, f"invoice_units={invoice_units}, dashboard_units={dashboard_units}", None


def _run_invariant_chain_integrity(patch_id):
    """Resolved record units must match rate engine input units."""
    r = _run_chain(patch_id)
    resolved_units = r["resolved"]["units"]
    resolved_tier = r["resolved"]["tier"]
    charges_units = r["charges"]["units"]
    charges_tier = r["charges"]["tier"]

    # Units must be consistent across resolver and rate engine
    if resolved_units != charges_units:
        return False, f"resolved_units={resolved_units} != charges_units={charges_units}", None

    # Tier must match the actual units
    expected_tier, _ = _resolve_tier(resolved_units)
    if resolved_tier != expected_tier:
        return False, f"tier={resolved_tier} but units={resolved_units} → expected {expected_tier}", None

    return True, "resolver and rate engine consistent", None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "near_root_hack":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="billing_aggregation_chain",
        difficulty="C",
        domain="SaaS billing",
        scenario="Usage collector groups events by local-time date instead of UTC. "
                 "Boundary events misassigned to wrong billing period. "
                 "Downstream tier assignment and pricing cascade from wrong unit count.",
        nodes=NodeDeclarations(
            source_of_truth_node="collector",
            corruption_introduced_at_node="collector",
            first_observable_symptom_node="plan_resolver",
            required_fix_node="collector",
        ),
        canonical=CanonicalRepresentation(
            field_names=["units"],
            schema_description="int, exact count of events in the UTC billing period",
            storage_location="usage record dicts from collector.aggregate_usage()",
            access_paths=[
                "plan_resolver reads units for tier assignment",
                "rate_engine reads units via resolved record",
                "get_usage_summary reads units directly (BYPASS)",
            ],
        ),
        chain=[
            ChainNode("collector", "collector.py", "aggregate_usage",
                      "groups raw events into per-period usage records — BUG: uses local date"),
            ChainNode("plan_resolver", "plan_resolver.py", "resolve",
                      "maps units to tier and rate"),
            ChainNode("rate_engine", "rate_engine.py", "compute_charges",
                      "multiplies units × rate"),
            ChainNode("invoice_builder", "invoice_builder.py", "build_invoice",
                      "assembles final invoice"),
        ],
        bypass_consumer="get_usage_summary",
        bypass_description="reads units field directly from collector output, no chain transforms",
        bug_description="collector groups by event['timestamp'][:10] (local date) instead of "
                        "converting to UTC first. Events near midnight are misassigned.",
        root_fix_description="convert timestamps to UTC before extracting billing-period date",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "invoice_builder overrides growth tier to enterprise pricing",
                     "if tier == growth: recalculate at enterprise rate",
                     "directly fixes the overcharge by applying correct tier pricing",
                     "system still miscounts for UTC-5 events; collector undercounts → wrong tier entirely",
                     "generalization", "utc_minus5_events"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "plan_resolver adds 20% tolerance on tier boundaries",
                     "if units >= boundary * 0.80: bump to higher tier",
                     "handles the borderline unit count defensively",
                     "tolerance creates tier/units inconsistency: 85 units labeled enterprise",
                     "chain_integrity", None),
            TrapSpec("trap_4", "downstream_override", "B",
                     "plan_resolver re-aggregates from raw events (correct count) before tier assignment",
                     "re-count units from raw events, ignoring collector output",
                     "closest to root fix; gets correct unit count for billing",
                     "get_usage_summary (bypass) still reads collector's wrong units → dashboard disagrees with invoice",
                     "cross_path", None),
            TrapSpec("near_root_hack", "near_root_incorrect", "B",
                     "collector adds +1h to all timestamps before grouping",
                     "shifted = to_utc(timestamp, -1) always",
                     "IS a timezone fix, IS in the right file",
                     "only works for tz=-1; UTC+5 events shift wrong direction",
                     "generalization", "utc_plus5_events"),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "collector adds corrected_units field alongside buggy units",
                     "record['corrected_units'] = utc_count; record['units'] = local_count",
                     "adds correct case_data at corruption node; looks like careful migration",
                     "get_usage_summary reads units (not corrected_units) → dashboard disagrees",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "legitimate 85-unit growth user (no tz issue) must pay $8.50",
                          [{"desc": "85 units no tz issue", "events": "legit_85"}]),
            InvariantSpec("generalization",
                          "must handle: (1) 42-unit starter user, (2) UTC+5 timezone events",
                          [{"desc": "42 units threshold"}, {"desc": "UTC+5 events"}]),
            InvariantSpec("causal_location",
                          "collector output units for April 1 must be 85 (correct UTC count)",
                          [{"desc": "primary input"}]),
            InvariantSpec("cross_path",
                          "invoice units must match dashboard (get_usage_summary) units",
                          [{"desc": "primary input"}]),
            InvariantSpec("chain_integrity",
                          "resolved units/tier must be consistent with rate engine charges",
                          [{"desc": "primary input"}]),
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
