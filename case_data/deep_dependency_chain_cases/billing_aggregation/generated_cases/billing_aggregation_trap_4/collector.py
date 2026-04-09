def aggregate_usage(dataset_dict):
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
