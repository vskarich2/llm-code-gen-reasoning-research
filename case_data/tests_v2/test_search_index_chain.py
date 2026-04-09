"""Tests for search_index_chain.

Bug: field_extractor includes metadata (id, author, created_at) in content_fields.
     Author names and doc IDs pollute the search index.
Fix: filter content_fields to CONTENT_KEYS only (title, body, tags).
"""


def test(mod):
    errors = []

    load_documents = getattr(mod, "load_documents", None)
    extract_fields = getattr(mod, "extract_fields", None)
    tokenize_node = getattr(mod, "tokenize_node", None)
    build_index_node = getattr(mod, "build_index_node", None)
    if not load_documents or not extract_fields or not tokenize_node or not build_index_node:
        return False, ["required functions not found: load_documents, extract_fields, tokenize_node, build_index_node"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    METADATA_KEYS = getattr(mod, "METADATA_KEYS", None)
    CONTENT_KEYS = getattr(mod, "CONTENT_KEYS", None)
    if RAW_DATA is None or METADATA_KEYS is None or CONTENT_KEYS is None:
        return False, ["RAW_DATA, METADATA_KEYS, or CONTENT_KEYS not found"]

    docs = load_documents(RAW_DATA["primary"])
    extracted = extract_fields(docs)

    # Invariant 1: content_fields must not contain metadata keys
    for edoc in extracted:
        metadata_leak = set(edoc["content_fields"].keys()) & METADATA_KEYS
        if metadata_leak:
            errors.append(f"invariant 1: {edoc['doc_id']} content_fields contains metadata: {sorted(metadata_leak)}")

    # Invariant 2: tags field must be present (not dropped)
    for edoc in extracted:
        if "tags" not in edoc["content_fields"]:
            errors.append(f"invariant 2: {edoc['doc_id']} missing 'tags' in content_fields")

    # Build index and test searches
    tokenized = tokenize_node(extracted)
    index_result = build_index_node(tokenized)
    index = index_result["index"] if isinstance(index_result, dict) else index_result

    # Invariant 3: author name not in index
    if "alice" in index:
        errors.append(f"invariant 3: author 'alice' found in index (metadata leak)")
    if "bob" in index:
        errors.append(f"invariant 3: author 'bob' found in index (metadata leak)")

    # Invariant 4: content tokens present
    if "python" not in index:
        errors.append("invariant 4: 'python' not in index (content missing)")
    if "javascript" not in index:
        errors.append("invariant 4: 'javascript' not in index (tag content missing)")

    return not errors, errors
