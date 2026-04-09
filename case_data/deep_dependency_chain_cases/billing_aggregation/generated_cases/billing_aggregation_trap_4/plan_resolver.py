from data import TIER_TABLE

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

def _resolve_tier(units):
    for tier_name, spec in TIER_TABLE.items():
        if spec["min"] <= units <= spec["max"]:
            return tier_name, spec["rate"]
    return "starter", 0.20

def resolve_plan(usage_records):
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
