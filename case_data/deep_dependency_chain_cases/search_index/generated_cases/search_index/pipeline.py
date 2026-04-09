from data import RAW_DATA
from loader import load_documents
from extractor import extract_fields
from tokenizer import tokenize_node
from indexer import build_index_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = load_documents(value)
    value = extract_fields(value)
    value = tokenize_node(value)
    value = build_index_node(value)
    return value
