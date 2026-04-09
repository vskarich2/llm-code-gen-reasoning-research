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

def aggregate_usage(dataset_dict):
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
