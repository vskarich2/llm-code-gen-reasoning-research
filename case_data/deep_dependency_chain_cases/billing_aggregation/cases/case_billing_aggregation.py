"""Case 2 (C): Billing aggregation chain.

Chain: collector → plan_resolver → rate_engine → invoice_builder
Bypass: get_usage_summary reads collector output directly
Bug: collector groups events by local-time date instead of UTC
Canonical field: units in usage record
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

TIER_TABLE = {
    "starter": {"min": 0, "max": 50, "rate": 0.20},
    "growth": {"min": 51, "max": 99, "rate": 0.10},
    "enterprise": {"min": 100, "max": 999999, "rate": 0.05},
}

_PRIMARY_EVENTS = (
    [{"ts": "2026-04-01T12:00:00", "units": 1}] * 85 +
    [{"ts": "2026-04-02T00:30:00", "units": 1}] * 15
)
_LEGIT_85_EVENTS = [{"ts": "2026-04-01T12:00:00", "units": 1}] * 85
_UTCm5_EVENTS = (
    [{"ts": "2026-04-01T12:00:00", "units": 1}] * 80 +
    [{"ts": "2026-04-01T23:00:00", "units": 1}] * 20
)

RAW_DATA = {
    "primary": {"events": _PRIMARY_EVENTS, "tz_offset": 1, "target_period": "2026-04-01"},
    "legit_85": {"events": _LEGIT_85_EVENTS, "tz_offset": 0, "target_period": "2026-04-01"},
    "utc_minus5": {"events": _UTCm5_EVENTS, "tz_offset": -5, "target_period": "2026-04-01"},
}

CASE_DATA_GLOBALS = ["TIER_TABLE", "RAW_DATA"]


def _to_utc(timestamp_str, tz_offset_hours):
    parts = timestamp_str.split("T")
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "00:00:00"
    h, m, s = [int(x) for x in time_part.split(":")]
    h -= tz_offset_hours
    if h >= 24:
        y, mo, d = [int(x) for x in date_part.split("-")]
        d += 1
        if d > 28:
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


def _collector_aggregate_buggy(events, tz_offset_hours=0):
    """BUG: groups by local date, not UTC."""
    by_period = {}
    for event in events:
        period = event["ts"][:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_fixed(events, tz_offset_hours=0):
    """ROOT FIX: convert to UTC before grouping."""
    by_period = {}
    for event in events:
        utc_ts = _to_utc(event["ts"], tz_offset_hours)
        period = utc_ts[:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_hack(events, tz_offset_hours=0):
    """NEAR-ROOT INCORRECT: always shifts by -1h."""
    by_period = {}
    for event in events:
        shifted = _to_utc(event["ts"], 1)
        period = shifted[:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


def _collector_aggregate_trap5(events, tz_offset_hours=0):
    """TRAP 5: adds corrected_units alongside buggy units."""
    buggy = _collector_aggregate_buggy(events, tz_offset_hours)
    fixed = _collector_aggregate_fixed(events, tz_offset_hours)
    fixed_map = {r["period"]: r["units"] for r in fixed}
    result = []
    for rec in buggy:
        rec["corrected_units"] = fixed_map.get(rec["period"], rec["units"])
        result.append(rec)
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
    """TRAP 1: endpoint compensation."""
    invoice = _invoice_builder_build(charges)
    if invoice["tier"] == "growth":
        invoice["tier"] = "enterprise"
        invoice["total"] = round(invoice["units"] * 0.05, 2)
        invoice["adjustment"] = "applied"
    return invoice


# ── Dispatch ──

PRIMARY_EVENTS = _PRIMARY_EVENTS
PRIMARY_TZ = 1
TARGET_PERIOD = "2026-04-01"
TRAP_CATCHING_EVENTS = _LEGIT_85_EVENTS
TRAP_CATCHING_TZ = 0
GENERALIZATION_EVENTS_TZM5 = _UTCm5_EVENTS
GENERALIZATION_TZ_M5 = -5
GENERALIZATION_EVENTS_42 = [{"ts": "2026-04-01T12:00:00", "units": 1} for _ in range(42)]
GENERALIZATION_42_TZ = 0


def _run_chain(patch_id, events=None, tz_offset=None):
    if events is None:
        events = PRIMARY_EVENTS
    if tz_offset is None:
        tz_offset = PRIMARY_TZ

    if patch_id == "root_fix":
        records = _collector_aggregate_fixed(events, tz_offset)
    elif patch_id == "near_root_hack":
        records = _collector_aggregate_hack(events, tz_offset)
    elif patch_id == "trap_5":
        records = _collector_aggregate_trap5(events, tz_offset)
    else:
        records = _collector_aggregate_buggy(events, tz_offset)

    target_rec = next((r for r in records if r["period"] == TARGET_PERIOD),
                      {"period": TARGET_PERIOD, "units": 0})

    summary = _get_usage_summary(records)

    if patch_id == "trap_3":
        resolved = _plan_resolver_resolve_tolerant(target_rec)
    elif patch_id == "trap_4":
        resolved = _plan_resolver_resolve_reaggregate(target_rec, events, tz_offset)
    elif patch_id == "trap_5":
        resolved = _plan_resolver_resolve(target_rec, use_corrected=True)
    else:
        resolved = _plan_resolver_resolve(target_rec)

    charges = _rate_engine_compute(resolved)

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
    return inv["total"] <= 6.00 and inv["total"] > 0


def _run_invariant_trap_catching(patch_id):
    r = _run_chain(patch_id, events=TRAP_CATCHING_EVENTS, tz_offset=TRAP_CATCHING_TZ)
    inv = r["invoice"]
    correct_total = 8.50
    passed = abs(inv["total"] - correct_total) < 0.10
    return passed, f"total={inv['total']}, expected={correct_total}", "legit_85_unit_user"


def _run_invariant_generalization(patch_id):
    r1 = _run_chain(patch_id, events=GENERALIZATION_EVENTS_42, tz_offset=GENERALIZATION_42_TZ)
    inv1 = r1["invoice"]
    correct_42 = 8.40
    if abs(inv1["total"] - correct_42) > 0.10:
        return False, f"42-unit: total={inv1['total']}, expected={correct_42}", "42_unit_threshold"

    r2 = _run_chain(patch_id, events=GENERALIZATION_EVENTS_TZM5, tz_offset=GENERALIZATION_TZ_M5)
    inv2 = r2["invoice"]
    correct_tzm5 = 8.00
    if abs(inv2["total"] - correct_tzm5) > 0.50:
        return False, f"UTC-5: total={inv2['total']}, expected~={correct_tzm5}", "utc_minus5_events"

    return True, "both generalization inputs pass", None


def _run_invariant_causal_location(patch_id):
    r = _run_chain(patch_id)
    collector_units = r["collector_units"]
    passed = collector_units == 100
    return passed, f"collector units={collector_units}, expected=100", None


def _run_invariant_cross_path(patch_id):
    r = _run_chain(patch_id)
    invoice_units = r["invoice"]["units"]
    dashboard_units = r["summary"].get(TARGET_PERIOD, 0)
    consistent = invoice_units == dashboard_units
    return consistent, f"invoice_units={invoice_units}, dashboard_units={dashboard_units}", None


def _run_invariant_chain_integrity(patch_id):
    r = _run_chain(patch_id)
    resolved_units = r["resolved"]["units"]
    resolved_tier = r["resolved"]["tier"]
    charges_units = r["charges"]["units"]
    charges_tier = r["charges"]["tier"]

    if resolved_units != charges_units:
        return False, f"resolved_units={resolved_units} != charges_units={charges_units}", None

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


# ── Compiler-compatible node functions ──

# @node: collector
# @role: buggy
def _aggregate_usage(dataset_dict):
    events = dataset_dict["events"]
    by_period = {}
    for event in events:
        period = event["ts"][:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


# @node: plan_resolver
# @role: main
def _resolve_plan(usage_records):
    if not usage_records:
        return {"period": "unknown", "units": 0, "tier": "starter", "rate": 0.20}
    top = max(usage_records, key=lambda r: r["units"])
    tier, rate = _resolve_tier(top["units"])
    return {"period": top["period"], "units": top["units"], "tier": tier, "rate": rate}


# @node: rate_engine
# @role: main
def _compute_charges(resolved):
    charge = resolved["units"] * resolved["rate"]
    return {"period": resolved["period"], "units": resolved["units"],
            "tier": resolved["tier"], "rate": resolved["rate"],
            "subtotal": round(charge, 2)}


# @node: invoice_builder
# @role: main
def _build_invoice(charges):
    return {"total": charges["subtotal"], "tier": charges["tier"],
            "units": charges["units"], "period": charges["period"]}


# @node: invoice_builder
# @role: trap_1
def _build_invoice_trap1(charges):
    invoice = {"total": charges["subtotal"], "tier": charges["tier"],
               "units": charges["units"], "period": charges["period"]}
    if invoice["tier"] == "growth" and invoice["total"] > 8.0:
        invoice["tier"] = "enterprise"
        invoice["total"] = round(invoice["units"] * 0.05, 2)
        invoice["adjustment"] = "applied"
    return invoice


# @node: collector
# @role: trap_3
def _aggregate_usage_trap3(dataset_dict):
    events = dataset_dict["events"]
    by_period = {}
    for event in events:
        shifted = _to_utc(event["ts"], 1)
        period = shifted[:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]


# @node: collector
# @role: trap_4
def _aggregate_usage_trap4(dataset_dict):
    events = dataset_dict["events"]
    tz_offset = dataset_dict.get("tz_offset", 0)
    by_period = {}
    for event in events:
        period = event["ts"][:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    records = []
    for p in sorted(by_period):
        records.append({
            "period": p,
            "units": by_period[p],
            "raw_events": list(events),
            "tz_offset": tz_offset,
        })
    return records


# @node: plan_resolver
# @role: trap_4
def _resolve_plan_trap4(usage_records):
    if not usage_records:
        return {"period": "unknown", "units": 0, "tier": "starter", "rate": 0.20}
    raw_events = usage_records[0].get("raw_events", [])
    tz_offset = usage_records[0].get("tz_offset", 0)
    if raw_events:
        by_period = {}
        for event in raw_events:
            utc_ts = _to_utc(event["ts"], tz_offset)
            period = utc_ts[:10]
            by_period[period] = by_period.get(period, 0) + event["units"]
        correct_records = [{"period": p, "units": u} for p, u in sorted(by_period.items())]
        top = max(correct_records, key=lambda r: r["units"])
    else:
        top = max(usage_records, key=lambda r: r["units"])
    tier, rate = _resolve_tier(top["units"])
    return {"period": top["period"], "units": top["units"], "tier": tier, "rate": rate}


# @node: collector
# @role: trap_5
def _aggregate_usage_trap5(dataset_dict):
    events = dataset_dict["events"]
    tz_offset = dataset_dict.get("tz_offset", 0)
    buggy_by_period = {}
    for event in events:
        period = event["ts"][:10]
        buggy_by_period[period] = buggy_by_period.get(period, 0) + event["units"]
    fixed_by_period = {}
    for event in events:
        utc_ts = _to_utc(event["ts"], tz_offset)
        period = utc_ts[:10]
        fixed_by_period[period] = fixed_by_period.get(period, 0) + event["units"]
    all_periods = sorted(set(buggy_by_period) | set(fixed_by_period))
    result = []
    for p in all_periods:
        result.append({
            "period": p,
            "units": buggy_by_period.get(p, 0),
            "corrected_units": fixed_by_period.get(p, 0),
        })
    return result


# @node: plan_resolver
# @role: trap_5
def _resolve_plan_trap5(usage_records):
    if not usage_records:
        return {"period": "unknown", "units": 0, "tier": "starter", "rate": 0.20}
    top = max(usage_records, key=lambda r: r.get("corrected_units", r["units"]))
    units = top.get("corrected_units", top["units"])
    tier, rate = _resolve_tier(units)
    return {"period": top["period"], "units": units, "tier": tier, "rate": rate}


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
            ChainNode("plan_resolver", "plan_resolver.py", "resolve_plan",
                      "maps units to tier and rate"),
            ChainNode("rate_engine", "rate_engine.py", "compute_charges",
                      "multiplies units × rate"),
            ChainNode("invoice_builder", "invoice_builder.py", "build_invoice",
                      "assembles final invoice"),
        ],
        bypass_consumer="get_usage_summary",
        bypass_description="reads units field directly from collector output, no chain transforms",
        bug_description="collector groups by event['ts'][:10] (local date) instead of "
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
                     "adds correct data at corruption node; looks like careful migration",
                     "get_usage_summary reads units (not corrected_units) → dashboard disagrees",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "legitimate 85-unit growth user (no tz issue) must pay $8.50",
                          [{"desc": "85 units no tz issue", "events": "legit_85"}]),
            InvariantSpec("generalization",
                          "must handle: (1) 42-unit starter user, (2) UTC-5 timezone events",
                          [{"desc": "42 units threshold"}, {"desc": "UTC-5 events"}]),
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
