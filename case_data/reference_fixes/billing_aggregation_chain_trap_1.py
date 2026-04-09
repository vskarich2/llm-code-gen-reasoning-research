def _to_utc(timestamp_str, tz_offset_hours):
    parts = timestamp_str.split("T")
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "00:00:00"
    h, m, s = [int(x) for x in time_part.split(":")]
    h -= tz_offset_hours
    y, mo, d = [int(x) for x in date_part.split("-")]
    if h < 0:
        h += 24
        d -= 1
        if d < 1:
            mo -= 1
            if mo < 1:
                mo = 12
                y -= 1
            d = 28
    elif h >= 24:
        h -= 24
        d += 1
        if d > 28:
            mo += 1
            if mo > 12:
                mo = 1
                y += 1
            d = 1
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{m:02d}:{s:02d}"


def aggregate_usage(dataset_dict):
    events = dataset_dict["events"]
    tz_offset = dataset_dict.get("tz_offset", 0)
    by_period = {}
    for event in events:
        utc_ts = _to_utc(event["ts"], tz_offset)
        period = utc_ts[:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]
