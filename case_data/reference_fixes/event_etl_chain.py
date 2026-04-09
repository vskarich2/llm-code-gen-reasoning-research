def normalize(events):
    result = []
    for event in events:
        normalized = {
            "event_type": event["event_type"].lower(),
            "user_id": event["user_id"],
            "amount": event["amount"],
            "currency": event["currency"].lower() if isinstance(event["currency"], str) else event["currency"],
        }
        result.append(normalized)
    return result
