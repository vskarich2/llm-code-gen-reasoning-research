def tokenize_node(extracted_docs):
    result = []
    for edoc in extracted_docs:
        source = edoc.get("clean_content", edoc.get("content_fields", {}))
        tokens = set()
        for value in source.values():
            for word in value.lower().split():
                if len(word) > 1:
                    tokens.add(word)
        result.append({"doc_id": edoc["doc_id"], "tokens": tokens})
    return result
