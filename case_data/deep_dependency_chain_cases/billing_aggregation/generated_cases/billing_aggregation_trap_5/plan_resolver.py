from data import TIER_TABLE

def _resolve_tier(units):
    for tier_name, spec in TIER_TABLE.items():
        if spec["min"] <= units <= spec["max"]:
            return tier_name, spec["rate"]
    return "starter", 0.20

def resolve_plan(usage_records):
    if not usage_records:
        return {"period": "unknown", "units": 0, "tier": "starter", "rate": 0.20}
    top = max(usage_records, key=lambda r: r.get("corrected_units", r["units"]))
    units = top.get("corrected_units", top["units"])
    tier, rate = _resolve_tier(units)
    return {"period": top["period"], "units": units, "tier": tier, "rate": rate}
