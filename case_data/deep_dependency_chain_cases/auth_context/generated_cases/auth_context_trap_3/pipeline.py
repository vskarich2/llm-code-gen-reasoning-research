from data import RAW_DATA
from token_parser import parse_token
from normalizer import normalize_context
from resolver import resolve_permissions_node
from gate import check_gate_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = parse_token(value)
    value = normalize_context(value)
    value = resolve_permissions_node(value)
    value = check_gate_node(value)
    return value
