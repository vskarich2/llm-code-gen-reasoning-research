from data import EPOCH_TABLE, EPOCH_TO_ISO

def serialize(records):
    result = []
    for record in records:
        iso = record["created_at"]
        epoch = EPOCH_TABLE.get(iso, 0)
        reconverted = EPOCH_TO_ISO.get(epoch, str(epoch)).replace("T", " ")
        result.append({
            "id": record["id"],
            "name": record["name"],
            "created_at": reconverted,
            "value": record["value"],
        })
    return result
