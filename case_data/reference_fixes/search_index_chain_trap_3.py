from data import CONTENT_KEYS


def extract_fields(documents):
    result = []
    for doc in documents:
        content_fields = {}
        for key, value in doc.items():
            if key not in CONTENT_KEYS:
                continue
            if isinstance(value, str):
                content_fields[key] = value
        result.append({"doc_id": doc["id"], "content_fields": content_fields})
    return result
