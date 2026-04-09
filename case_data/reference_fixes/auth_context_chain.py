def normalize_context(parsed):
    result = dict(parsed)
    result["action"] = result["action"].lower()
    return result
