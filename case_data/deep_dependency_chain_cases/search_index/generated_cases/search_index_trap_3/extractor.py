def extract_fields(documents):
    result = []
    HARDCODED_CONTENT = {"title", "body"}
    for doc in documents:
        content_fields = {}
        for key, value in doc.items():
            if key not in HARDCODED_CONTENT:
                continue
            if isinstance(value, str):
                content_fields[key] = value
        result.append({"doc_id": doc["id"], "content_fields": content_fields})
    return result
