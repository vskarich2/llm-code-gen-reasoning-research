def serialize(records):
    result = []
    for record in records:
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": record["created_at"],
            "value": record["value"],
        })
    return result
