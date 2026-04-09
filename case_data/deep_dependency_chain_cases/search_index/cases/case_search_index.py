"""Case 3 (B): Search index pipeline.

Chain: document_loader → field_extractor → tokenizer → index_builder
Bypass: get_raw_fields reads field_extractor output directly
Bug: field_extractor includes metadata fields (timestamps, IDs) in the content field
Canonical field: content_fields in extracted record
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

DOCUMENTS = {
    "doc1": {
        "id": "doc1",
        "title": "Python Guide",
        "body": "Learn Python programming with examples",
        "author": "alice",
        "created_at": "20260115",
        "tags": "python tutorial",
    },
    "doc2": {
        "id": "doc2",
        "title": "Data Science Intro",
        "body": "Statistics and machine learning basics",
        "author": "bob",
        "created_at": "20260220",
        "tags": "data ml",
    },
    "doc3": {
        "id": "doc3",
        "title": "Web Development",
        "body": "Building modern web applications",
        "author": "carol",
        "created_at": "20260310",
        "tags": "web javascript",
    },
}

CONTENT_KEYS = {"title", "body", "tags"}
METADATA_KEYS = {"id", "author", "created_at"}

RAW_DATA = {
    "primary": ["doc1", "doc2", "doc3"],
}

CASE_DATA_GLOBALS = ["DOCUMENTS", "CONTENT_KEYS", "METADATA_KEYS", "RAW_DATA"]


def _load_document(doc_id):
    return DOCUMENTS.get(doc_id)


def _extract_fields_buggy(doc):
    """BUG: includes metadata fields in content_fields."""
    content_fields = {}
    for key, value in doc.items():
        if isinstance(value, str):
            content_fields[key] = value
        elif isinstance(value, list):
            content_fields[key] = " ".join(str(v) for v in value)
    return {"doc_id": doc["id"], "content_fields": content_fields}


def _extract_fields_fixed(doc):
    """ROOT FIX: only include content keys in content_fields."""
    content_fields = {}
    for key, value in doc.items():
        if key not in CONTENT_KEYS:
            continue
        if isinstance(value, str):
            content_fields[key] = value
        elif isinstance(value, list):
            content_fields[key] = " ".join(str(v) for v in value)
    return {"doc_id": doc["id"], "content_fields": content_fields}


def _extract_fields_trap5(doc):
    """TRAP 5: adds clean_content alongside buggy content_fields."""
    buggy = _extract_fields_buggy(doc)
    clean = {}
    for key, value in doc.items():
        if key not in CONTENT_KEYS:
            continue
        if isinstance(value, str):
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = " ".join(str(v) for v in value)
    buggy["clean_content"] = clean
    return buggy


def _split_tokens(text):
    tokens = set()
    for word in text.lower().split():
        if len(word) > 1:
            tokens.add(word)
    return tokens


def _tokenize(extracted):
    tokens = set()
    source = extracted.get("content_fields", {})
    for key, value in source.items():
        tokens.update(_split_tokens(value))
    return {"doc_id": extracted["doc_id"], "tokens": tokens}


def _tokenize_from_clean(extracted):
    tokens = set()
    source = extracted.get("clean_content", extracted.get("content_fields", {}))
    for key, value in source.items():
        tokens.update(_split_tokens(value))
    return {"doc_id": extracted["doc_id"], "tokens": tokens}


def _extract_fields_trap3(doc):
    """TRAP 3: extractor filters to hardcoded {title, body}, drops tags."""
    content_fields = {}
    HARDCODED_CONTENT = {"title", "body"}
    for key, value in doc.items():
        if key not in HARDCODED_CONTENT:
            continue
        if isinstance(value, str):
            content_fields[key] = value
        elif isinstance(value, list):
            content_fields[key] = " ".join(str(v) for v in value)
    return {"doc_id": doc["id"], "content_fields": content_fields}


def _build_index(tokenized_docs):
    index = {}
    for tdoc in tokenized_docs:
        for token in tdoc["tokens"]:
            index.setdefault(token, set()).add(tdoc["doc_id"])
    return index


def _search(index, query):
    query_tokens = _split_tokens(query)
    if not query_tokens:
        return set()
    result = None
    for token in query_tokens:
        matches = index.get(token, set())
        result = set(matches) if result is None else result & matches
    return result or set()


def _get_raw_fields(extracted_docs):
    """BYPASS CONSUMER: reads content_fields keys directly from extractor output."""
    result = {}
    for edoc in extracted_docs:
        result[edoc["doc_id"]] = set(edoc["content_fields"].keys())
    return result


# ── Dispatch ──

ALL_DOC_IDS = ["doc1", "doc2", "doc3"]


def _run_chain(patch_id, doc_ids=None):
    if doc_ids is None:
        doc_ids = ALL_DOC_IDS

    docs = [_load_document(did) for did in doc_ids]

    extracted = []
    for doc in docs:
        if patch_id == "root_fix":
            extracted.append(_extract_fields_fixed(doc))
        elif patch_id == "trap_3":
            extracted.append(_extract_fields_trap3(doc))
        elif patch_id == "trap_5":
            extracted.append(_extract_fields_trap5(doc))
        else:
            extracted.append(_extract_fields_buggy(doc))

    raw_fields = _get_raw_fields(extracted)

    tokenized = []
    for edoc in extracted:
        if patch_id == "trap_5":
            tokenized.append(_tokenize_from_clean(edoc))
        else:
            tokenized.append(_tokenize(edoc))

    index = _build_index(tokenized)

    if patch_id == "trap_1":
        def filtered_search(query):
            query_tokens = {w.lower() for w in query.split()
                           if len(w) > 1 and not any(c.isdigit() for c in w)}
            if not query_tokens:
                return set()
            result = None
            for token in query_tokens:
                matches = index.get(token, set())
                result = set(matches) if result is None else result & matches
            return result or set()
        search_fn = filtered_search
    else:
        search_fn = lambda q: _search(index, q)

    if patch_id == "trap_4":
        tokenized_clean = []
        for doc in docs:
            clean_extracted = _extract_fields_fixed(doc)
            tokenized_clean.append(_tokenize(clean_extracted))
        index = _build_index(tokenized_clean)
        search_fn = lambda q: _search(index, q)

    return {
        "search_fn": search_fn,
        "index": index,
        "raw_fields": raw_fields,
        "extracted": extracted,
        "tokenized": tokenized,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id)
    results = r["search_fn"]("python")
    if "doc1" not in results:
        return False
    results_meta = r["search_fn"]("alice")
    if results_meta:
        return False
    return True


def _run_invariant_trap_catching(patch_id):
    r = _run_chain(patch_id)
    results = r["search_fn"]("bob")
    if results:
        return False, f"search('bob') returned {results}, expected empty", "author_metadata"
    return True, "author metadata not in search results", "author_metadata"


def _run_invariant_generalization(patch_id):
    r = _run_chain(patch_id)
    results = r["search_fn"]("learning")
    if "doc2" not in results:
        return False, f"search('learning') = {results}, expected doc2", "content_search"
    results2 = r["search_fn"]("javascript")
    if "doc3" not in results2:
        return False, f"search('javascript') = {results2}, expected doc3", "tag_search"
    return True, "content search works correctly", None


def _run_invariant_causal_location(patch_id):
    r = _run_chain(patch_id)
    for edoc in r["extracted"]:
        field_keys = set(edoc["content_fields"].keys())
        metadata_leak = field_keys & METADATA_KEYS
        if metadata_leak:
            return False, f"doc {edoc['doc_id']}: content_fields contains metadata: {metadata_leak}", None
    return True, "content_fields contains only content keys", None


def _run_invariant_cross_path(patch_id):
    r = _run_chain(patch_id)
    bypass_has_metadata = any(
        bool(fields & METADATA_KEYS) for fields in r["raw_fields"].values()
    )
    metadata_tokens = {"alice", "bob", "carol", "doc1", "doc2", "doc3"}
    index_has_metadata = bool(metadata_tokens & set(r["index"].keys()))

    if bypass_has_metadata != index_has_metadata:
        return False, (f"INCONSISTENCY: bypass_metadata={bypass_has_metadata}, "
                       f"index_metadata={index_has_metadata}"), None
    return True, "bypass and index consistent on metadata presence", None


def _run_invariant_chain_integrity(patch_id):
    r = _run_chain(patch_id)
    for i, edoc in enumerate(r["extracted"]):
        tdoc = r["tokenized"][i]
        content_text = " ".join(edoc["content_fields"].values()).lower()
        for token in tdoc["tokens"]:
            if token not in content_text:
                return False, f"token '{token}' not in content_fields of {edoc['doc_id']}", None
    return True, "tokens consistent with content_fields", None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


# ── Compiler-compatible node functions ──

# @node: document_loader
# @role: main
def _load_documents(doc_ids):
    return [dict(DOCUMENTS[did]) for did in doc_ids]


# @node: field_extractor
# @role: buggy
def _extract_fields(documents):
    result = []
    for doc in documents:
        content_fields = {}
        for key, value in doc.items():
            if isinstance(value, str):
                content_fields[key] = value
        result.append({"doc_id": doc["id"], "content_fields": content_fields})
    return result


# @node: tokenizer
# @role: main
def _tokenize_node(extracted_docs):
    result = []
    for edoc in extracted_docs:
        tokens = set()
        for value in edoc["content_fields"].values():
            for word in value.lower().split():
                if len(word) > 1:
                    tokens.add(word)
        result.append({"doc_id": edoc["doc_id"], "tokens": tokens})
    return result


# @node: index_builder
# @role: main
def _build_index_node(tokenized_docs):
    index = {}
    for tdoc in tokenized_docs:
        for token in tdoc["tokens"]:
            if token not in index:
                index[token] = set()
            index[token].add(tdoc["doc_id"])
    return {"index": index, "doc_count": len(tokenized_docs)}


# @node: field_extractor
# @role: trap_3
def _extract_fields_trap3_node(documents):
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


# @node: field_extractor
# @role: trap_5
def _extract_fields_trap5_node(documents):
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


# @node: tokenizer
# @role: trap_5
def _tokenize_from_clean_node(extracted_docs):
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


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="search_index_chain",
        difficulty="B",
        domain="search/indexing",
        scenario="Document search pipeline where field extractor includes metadata "
                 "(IDs, timestamps, authors) in content fields. Metadata pollutes the "
                 "search index, causing false positive matches.",
        nodes=NodeDeclarations(
            source_of_truth_node="document_loader",
            corruption_introduced_at_node="field_extractor",
            first_observable_symptom_node="tokenizer",
            required_fix_node="field_extractor",
        ),
        canonical=CanonicalRepresentation(
            field_names=["content_fields"],
            schema_description="dict with keys from CONTENT_KEYS only (title, body, tags)",
            storage_location="extracted record dict from field_extractor",
            access_paths=[
                "tokenizer reads content_fields for token extraction",
                "index_builder reads tokens derived from content_fields",
                "get_raw_fields reads content_fields keys directly (BYPASS)",
            ],
        ),
        chain=[
            ChainNode("document_loader", "loader.py", "load_documents",
                      "loads raw documents by dataset key"),
            ChainNode("field_extractor", "extractor.py", "extract_fields",
                      "extracts content fields — BUG: includes metadata"),
            ChainNode("tokenizer", "tokenizer.py", "tokenize_node",
                      "splits content_fields values into lowercase token sets"),
            ChainNode("index_builder", "indexer.py", "build_index_node",
                      "builds inverted index from token sets"),
        ],
        bypass_consumer="get_raw_fields",
        bypass_description="reads content_fields keys directly from extractor output; "
                           "no tokenizer or index_builder calls; no shared logic",
        bug_description="field_extractor includes metadata keys (id, author, created_at) "
                        "in content_fields dict. Metadata tokens pollute the search index.",
        root_fix_description="filter content_fields to only include CONTENT_KEYS (title, body, tags)",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "search function filters numeric/metadata tokens from queries",
                     "strip tokens matching metadata patterns from query before lookup",
                     "directly prevents metadata matches in search results",
                     "non-numeric metadata (author 'bob') still matches; index analytics wrong",
                     "trap_catching", "author_metadata"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "extractor hardcodes content keys to {title, body}, dropping tags",
                     "only extract title and body, skip all other fields",
                     "removes all metadata from content_fields by restricting to known keys",
                     "drops tags field — tag-based searches (javascript, ml) fail",
                     "generalization", "tag_search"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "index_builder re-extracts clean content before indexing",
                     "re-run field extraction with content-only filter before building index",
                     "produces clean index; appears to solve the problem",
                     "get_raw_fields (bypass) still reads buggy content_fields from extractor",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "extractor adds clean_fields alongside buggy content_fields",
                     "extracted['clean_content'] = {content-only fields}; content_fields unchanged",
                     "correct data available at extractor node; looks like careful migration",
                     "tokenizer reads content_fields (polluted), not clean_content",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "search for non-numeric metadata (author name) must return empty",
                          [{"desc": "search for author 'bob'"}]),
            InvariantSpec("generalization",
                          "legitimate content searches must return correct results",
                          [{"desc": "search 'learning' → doc2"},
                           {"desc": "search 'javascript' → doc3"}]),
            InvariantSpec("causal_location",
                          "extractor content_fields must contain only CONTENT_KEYS",
                          [{"desc": "check field keys against CONTENT_KEYS"}]),
            InvariantSpec("cross_path",
                          "bypass raw_fields must be consistent with index content",
                          [{"desc": "raw_fields metadata presence matches index metadata presence"}]),
            InvariantSpec("chain_integrity",
                          "all tokens must come from content_fields values",
                          [{"desc": "every token is substring of content_fields text"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
