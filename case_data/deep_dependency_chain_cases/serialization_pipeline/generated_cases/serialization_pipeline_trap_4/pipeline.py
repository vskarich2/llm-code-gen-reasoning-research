from data import RAW_DATA
from builder import build_records_node
from serializer import serialize
from compressor import compress_node
from transport import transport_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = build_records_node(value)
    value = serialize(value)
    value = compress_node(value)
    value = transport_node(value)
    return value
