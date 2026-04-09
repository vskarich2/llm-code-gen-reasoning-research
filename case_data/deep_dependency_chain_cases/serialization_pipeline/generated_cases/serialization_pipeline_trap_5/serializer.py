from data import EPOCH_TABLE

def serialize(records):
    result = []
    for record in records:
        iso = record["created_at"]
        epoch = EPOCH_TABLE.get(iso, 0)
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": epoch,
            "created_at_iso": iso,
            "value": record["value"],
        })
    return result
