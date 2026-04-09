def tokenize_node(extracted_docs):
    result = []
    for edoc in extracted_docs:
        tokens = set()
        for value in edoc["content_fields"].values():
            for word in value.lower().split():
                if len(word) > 1:
                    tokens.add(word)
        result.append({"doc_id": edoc["doc_id"], "tokens": tokens})
    return result
