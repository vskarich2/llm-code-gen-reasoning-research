def normalize(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            normalized[k] = v.lower() if isinstance(v, str) else v
        result.append(normalized)
    return result
