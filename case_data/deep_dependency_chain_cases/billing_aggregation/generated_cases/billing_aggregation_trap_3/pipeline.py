from data import RAW_DATA
from collector import aggregate_usage
from plan_resolver import resolve_plan
from rate_engine import compute_charges
from invoice_builder import build_invoice


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = aggregate_usage(value)
    value = resolve_plan(value)
    value = compute_charges(value)
    value = build_invoice(value)
    return value
