"""Case 3 (B): Search index pipeline.

Chain: document_loader → field_extractor → tokenizer → index_builder
Bypass: get_raw_fields reads field_extractor output directly
Bug: field_extractor includes metadata fields (timestamps, IDs) in the content field
Canonical field: content_fields in extracted record
"""

from data.deep_dependency_chain.spec_types import (
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
        "created_at": "2026-01-15T10:00:00",
        "tags": ["python", "tutorial"],
    },
    "doc2": {
        "id": "doc2",
        "title": "Data Science Intro",
        "body": "Statistics and machine learning basics",
        "author": "bob",
        "created_at": "2026-02-20T14:30:00",
        "tags": ["case_data", "ml"],
    },
    "doc3": {
        "id": "doc3",
        "title": "Web Development",
        "body": "Building modern web applications",
        "author": "carol",
        "created_at": "2026-03-10T09:15:00",
        "tags": ["web", "javascript"],
    },
}

CONTENT_KEYS = {"title", "body", "tags"}
METADATA_KEYS = {"id", "author", "created_at"}


def _load_document(doc_id):
    return DOCUMENTS.get(doc_id)


def _extract_fields_buggy(doc):
    """BUG: includes metadata fields in content_fields."""
    content_fields = {}
    for key, value in doc.items():
        # Bug: does not filter out metadata — includes id, author, created_at
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
    buggy["clean_content"] = clean  # alternate field
    return buggy


def _split_tokens(text):
    """Split text into tokens on whitespace and common delimiters."""
    import re
    return [w for w in re.split(r'[\s\-_/:@.,:;!?\"\'()\[\]{}]+', text.lower()) if len(w) > 1]


def _tokenize(extracted):
    """Tokenizes all values in content_fields into lowercase tokens."""
    tokens = set()
    source = extracted.get("content_fields", {})
    for key, value in source.items():
        for word in _split_tokens(value):
            tokens.add(word)
    return {"doc_id": extracted["doc_id"], "tokens": tokens}


def _extract_fields_trap3(doc):
    """TRAP 3: extractor filters to hardcoded subset of content keys.
    Only includes 'title' and 'body', drops 'tags'. Fixes metadata leak
    but loses tag content."""
    content_fields = {}
    HARDCODED_CONTENT = {"title", "body"}  # missing "tags"
    for key, value in doc.items():
        if key not in HARDCODED_CONTENT:
            continue
        if isinstance(value, str):
            content_fields[key] = value
        elif isinstance(value, list):
            content_fields[key] = " ".join(str(v) for v in value)
    return {"doc_id": doc["id"], "content_fields": content_fields}


def _tokenize_from_clean(extracted):
    """For trap 5: tokenize from clean_content instead of content_fields."""
    tokens = set()
    source = extracted.get("clean_content", extracted.get("content_fields", {}))
    for key, value in source.items():
        for word in _split_tokens(value):
            tokens.add(word)
    return {"doc_id": extracted["doc_id"], "tokens": tokens}


def _build_index(tokenized_docs):
    """Builds inverted index: token → set of doc_ids."""
    index = {}
    for tdoc in tokenized_docs:
        for token in tdoc["tokens"]:
            index.setdefault(token, set()).add(tdoc["doc_id"])
    return index


def _search(index, query):
    """Returns doc_ids matching all query tokens."""
    query_tokens = set(_split_tokens(query))
    if not query_tokens:
        return set()
    result = None
    for token in query_tokens:
        matches = index.get(token, set())
        if result is None:
            result = set(matches)
        else:
            result &= matches
    return result or set()


def _get_raw_fields(extracted_docs):
    """BYPASS CONSUMER: reads content_fields directly from extractor output.
    Used for field-level analytics. Must NOT contain metadata."""
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

    # Step A/B: extract fields
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

    # Bypass consumer
    raw_fields = _get_raw_fields(extracted)

    # Step C: tokenize
    tokenized = []
    for edoc in extracted:
        if patch_id == "trap_5":
            tokenized.append(_tokenize_from_clean(edoc))
        else:
            tokenized.append(_tokenize(edoc))

    # Step D: build index + search
    index = _build_index(tokenized)

    if patch_id == "trap_1":
        # Endpoint: filter tokens containing digits from search queries
        # Handles timestamp fragments like "2026" but NOT author names like "bob"
        def filtered_search(query):
            query_tokens = {w.lower().strip() for w in query.split()
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
        # Downstream override: index_builder re-extracts content fields before indexing
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


# ── Test inputs ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id)
    # Search "python" should return doc1
    results = r["search_fn"]("python")
    if "doc1" not in results:
        return False
    # Search "2026" (timestamp year, metadata) should return NOTHING
    results_meta = r["search_fn"]("2026")
    if results_meta:
        return False  # metadata leaked into index
    return True


def _run_invariant_trap_catching(patch_id):
    """Search for "2026" (a timestamp fragment). Must return empty.
    Trap 1 filters numeric tokens from QUERIES but the index still contains them.
    Search for a non-numeric metadata token like author name."""
    r = _run_chain(patch_id)
    # "bob" is an author (metadata). Should not be in index.
    results = r["search_fn"]("bob")
    if results:
        return False, f"search('bob') returned {results}, expected empty (metadata leak)", "author_metadata"
    return True, "author metadata not in search results", "author_metadata"


def _run_invariant_generalization(patch_id):
    """Search for content that exists across documents.
    Test that legitimate content tokens are NOT filtered out."""
    r = _run_chain(patch_id)
    # "learning" appears in doc2 body: "machine learning basics"
    results = r["search_fn"]("learning")
    if "doc2" not in results:
        return False, f"search('learning') = {results}, expected doc2", "content_search"
    # "javascript" appears ONLY in doc3 tags (not in title or body)
    results2 = r["search_fn"]("javascript")
    if "doc3" not in results2:
        return False, f"search('javascript') = {results2}, expected doc3", "tag_search"
    return True, "content search works correctly", None


def _run_invariant_causal_location(patch_id):
    """Extractor output content_fields must contain ONLY content keys."""
    r = _run_chain(patch_id)
    for edoc in r["extracted"]:
        field_keys = set(edoc["content_fields"].keys())
        metadata_leak = field_keys & METADATA_KEYS
        if metadata_leak:
            return False, f"doc {edoc['doc_id']}: content_fields contains metadata: {metadata_leak}", None
    return True, "content_fields contains only content keys", None


def _run_invariant_cross_path(patch_id):
    """Bypass raw_fields must be CONSISTENT with search index content.
    Cross-path fires only when the two paths DISAGREE — one appears clean,
    the other shows metadata. If both are wrong together, that's not a
    cross-path failure (it's causal-location or generalization)."""
    r = _run_chain(patch_id)
    bypass_has_metadata = any(
        bool(fields & METADATA_KEYS) for fields in r["raw_fields"].values()
    )
    # Check if index contains metadata tokens (author names, doc IDs)
    metadata_tokens = {"alice", "bob", "carol", "doc1", "doc2", "doc3"}
    index_has_metadata = bool(metadata_tokens & set(r["index"].keys()))

    if bypass_has_metadata != index_has_metadata:
        return False, (f"INCONSISTENCY: bypass_metadata={bypass_has_metadata}, "
                       f"index_metadata={index_has_metadata}"), None
    return True, "bypass and index consistent on metadata presence", None


def _run_invariant_chain_integrity(patch_id):
    """Token sets must be consistent with extractor output.
    If tokenizer filters metadata but extractor still includes it,
    the token count will be less than expected from content_fields."""
    r = _run_chain(patch_id)
    for i, edoc in enumerate(r["extracted"]):
        tdoc = r["tokenized"][i]
        # Every token should come from content_fields values
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
            ChainNode("document_loader", "loader.py", "load_document",
                      "loads raw document by ID"),
            ChainNode("field_extractor", "extractor.py", "extract_fields",
                      "extracts content fields — BUG: includes metadata"),
            ChainNode("tokenizer", "tokenizer.py", "tokenize",
                      "splits content_fields values into token set"),
            ChainNode("index_builder", "indexer.py", "build_index",
                      "builds inverted index from tokens"),
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
                     "non-numeric metadata (author 'bob') still matches; also query "
                     "filtering doesn't fix the index — analytics on index are wrong",
                     "trap_catching", "author_metadata"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "extractor hardcodes content keys to {title, body}, dropping tags",
                     "only extract title and body, skip all other fields",
                     "removes all metadata from content_fields by restricting to known keys",
                     "drops tags field — tag-based searches (e.g., 'web', 'ml') fail",
                     "generalization", "tag_search"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "index_builder re-extracts clean content before indexing",
                     "re-run field extraction with content-only filter before building index",
                     "produces clean index; appears to solve the problem",
                     "get_raw_fields (bypass) still reads buggy content_fields from extractor; "
                     "field analytics report metadata as content",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "extractor adds clean_content field alongside buggy content_fields",
                     "extracted['clean_content'] = {content-only fields}; content_fields unchanged",
                     "correct case_data available at extractor node; looks like careful migration",
                     "get_raw_fields reads content_fields (not clean_content); "
                     "field analytics still report metadata",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "search for non-numeric metadata (author name) must return empty",
                          [{"desc": "search for author 'bob'"}]),
            InvariantSpec("generalization",
                          "legitimate content searches must return correct results",
                          [{"desc": "search 'learning' → doc2"},
                           {"desc": "search 'web' → doc3"}]),
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
