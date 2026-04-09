"""Tests for billing_aggregation_chain.

Bug: collector groups events by local date instead of UTC.
     15 boundary events (local Apr 2 / UTC Apr 1) misassigned.
     April 1 shows 85 units (growth) instead of 100 (enterprise).
Fix: convert timestamps to UTC using tz_offset before extracting date.
"""


def test(mod):
    errors = []

    aggregate_usage = getattr(mod, "aggregate_usage", None)
    resolve_plan = getattr(mod, "resolve_plan", None)
    compute_charges = getattr(mod, "compute_charges", None)
    build_invoice = getattr(mod, "build_invoice", None)
    if not aggregate_usage or not resolve_plan or not compute_charges or not build_invoice:
        return False, ["required functions not found: aggregate_usage, resolve_plan, compute_charges, build_invoice"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    if RAW_DATA is None:
        return False, ["RAW_DATA not found in module"]

    # Invariant 1: primary dataset — April 1 must have 100 units (UTC grouping)
    records = aggregate_usage(RAW_DATA["primary"])
    april1 = next((r for r in records if r["period"] == "2026-04-01"), None)
    if april1 is None:
        errors.append("invariant 1: no record for period 2026-04-01")
    elif april1["units"] != 100:
        errors.append(f"invariant 1: April 1 units={april1['units']}, expected 100 (UTC grouping)")

    # Invariant 2: full pipeline gives enterprise tier at $5.00
    if not errors:
        resolved = resolve_plan(records)
        charges = compute_charges(resolved)
        invoice = build_invoice(charges)
        if invoice["tier"] != "enterprise":
            errors.append(f"invariant 2: tier={invoice['tier']!r}, expected 'enterprise'")
        if abs(invoice["total"] - 5.00) > 0.10:
            errors.append(f"invariant 2: total={invoice['total']}, expected ~5.00")

    # Invariant 3: legit 85-unit user (no tz issue) stays growth at $8.50
    legit_records = aggregate_usage(RAW_DATA["legit_85"])
    legit_april1 = next((r for r in legit_records if r["period"] == "2026-04-01"), None)
    if legit_april1 and legit_april1["units"] != 85:
        errors.append(f"invariant 3: legit_85 units={legit_april1['units']}, expected 85")
    if legit_april1:
        legit_resolved = resolve_plan(legit_records)
        legit_charges = compute_charges(legit_resolved)
        legit_invoice = build_invoice(legit_charges)
        if legit_invoice["tier"] != "growth":
            errors.append(f"invariant 3: legit_85 tier={legit_invoice['tier']!r}, expected 'growth'")

    # Invariant 4: UTC-5 dataset — collector must use actual tz_offset, not hardcoded
    # 80 events at noon (UTC: noon+5=17:00 Apr 1) + 20 events at 23:00 (UTC: 04:00 Apr 2)
    # Correct UTC grouping: April 1 = 80 units
    utcm5_records = aggregate_usage(RAW_DATA["utc_minus5"])
    utcm5_april1 = next((r for r in utcm5_records if r["period"] == "2026-04-01"), None)
    if utcm5_april1 is None:
        errors.append("invariant 4: no record for 2026-04-01 in utc_minus5 dataset")
    elif utcm5_april1["units"] != 80:
        errors.append(f"invariant 4: utc_minus5 April 1 units={utcm5_april1['units']}, expected 80")

    return not errors, errors
