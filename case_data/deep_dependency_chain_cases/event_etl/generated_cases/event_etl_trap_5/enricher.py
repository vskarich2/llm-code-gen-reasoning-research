from data import USER_PROFILES

def enrich_node(normalized_events):
    result = []
    for event in normalized_events:
        uid = event.get("original_user_id", event["user_id"])
        profile = USER_PROFILES.get(uid)
        enriched = dict(event)
        if profile:
            enriched["tier"] = profile["tier"]
            enriched["region"] = profile["region"]
        else:
            enriched["tier"] = "unknown"
            enriched["region"] = "unknown"
        result.append(enriched)
    return result
