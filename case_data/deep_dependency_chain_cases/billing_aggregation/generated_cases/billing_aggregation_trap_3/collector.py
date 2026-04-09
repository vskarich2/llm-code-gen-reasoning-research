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
    by_period = {}
    for event in events:
        shifted = _to_utc(event["ts"], 1)
        period = shifted[:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]
