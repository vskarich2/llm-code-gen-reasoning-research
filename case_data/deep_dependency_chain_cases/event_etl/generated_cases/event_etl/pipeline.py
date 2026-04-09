from data import RAW_EVENTS
from source import load_events_node
from normalizer import normalize
from enricher import enrich_node
from writer import write_events


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = load_events_node(value)
    value = normalize(value)
    value = enrich_node(value)
    value = write_events(value)
    return value
