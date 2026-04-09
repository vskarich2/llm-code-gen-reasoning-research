def aggregate_usage(dataset_dict):
    events = dataset_dict["events"]
    by_period = {}
    for event in events:
        period = event["ts"][:10]
        by_period[period] = by_period.get(period, 0) + event["units"]
    return [{"period": p, "units": u} for p, u in sorted(by_period.items())]
