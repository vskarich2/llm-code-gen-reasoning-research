def write_events(enriched_events):
    result = []
    for event in enriched_events:
        result.append({
            "user_id": event["user_id"],
            "event_type": event["event_type"],
            "amount": float(event["amount"]) if isinstance(event["amount"], str) else event["amount"],
            "tier": event["tier"],
            "region": event["region"],
        })
    return result
