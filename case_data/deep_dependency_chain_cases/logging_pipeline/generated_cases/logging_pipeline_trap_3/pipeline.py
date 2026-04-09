from data import RAW_DATA
from collector import collect_events_node
from formatter import format_logs_node
from aggregator import aggregate_metrics_node
from dashboard import render_dashboard_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = collect_events_node(value)
    value = format_logs_node(value)
    value = aggregate_metrics_node(value)
    value = render_dashboard_node(value)
    return value
