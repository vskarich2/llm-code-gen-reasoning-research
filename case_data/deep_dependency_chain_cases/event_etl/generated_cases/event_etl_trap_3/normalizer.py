def normalize(events):
    result = []
    for event in events:
        normalized = {}
        for k, v in event.items():
            if isinstance(v, str):
                if "_" in v or "-" in v:
                    normalized[k] = v
                else:
                    normalized[k] = v.lower()
            else:
                normalized[k] = v
        result.append(normalized)
    return result
