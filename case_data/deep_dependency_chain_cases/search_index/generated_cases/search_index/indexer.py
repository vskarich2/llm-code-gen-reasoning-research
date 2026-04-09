def build_index_node(tokenized_docs):
    index = {}
    for tdoc in tokenized_docs:
        for token in tdoc["tokens"]:
            if token not in index:
                index[token] = set()
            index[token].add(tdoc["doc_id"])
    return {"index": index, "doc_count": len(tokenized_docs)}
