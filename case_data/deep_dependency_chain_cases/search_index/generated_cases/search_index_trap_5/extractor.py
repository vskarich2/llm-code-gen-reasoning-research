from data import CONTENT_KEYS

def extract_fields(documents):
    result = []
    for doc in documents:
        content_fields = {}
        clean_content = {}
        for key, value in doc.items():
            if isinstance(value, str):
                content_fields[key] = value
            if key in CONTENT_KEYS and isinstance(value, str):
                clean_content[key] = value
        result.append({"doc_id": doc["id"], "content_fields": content_fields, "clean_content": clean_content})
    return result
