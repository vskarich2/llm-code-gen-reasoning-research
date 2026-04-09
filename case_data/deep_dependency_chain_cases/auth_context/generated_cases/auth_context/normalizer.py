def normalize_context(parsed):
    result = dict(parsed)
    if "-" in result["org_id"]:
        result["org_id"] = result["org_id"].split("-", 1)[1]
    result["action"] = result["action"].lower()
    return result
