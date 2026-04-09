def normalize(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            normalized[k] = v.lower() if isinstance(v, str) else v
        normalized["original_user_id"] = event["user_id"]
        result.append(normalized)
    return result
