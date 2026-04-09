from data import RAW_DATA
from data_source import data_source_node
from features import feature_engineer_node
from scaler import scaler_node
from scorer import model_scorer_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = data_source_node(value)
    value = feature_engineer_node(value)
    value = scaler_node(value)
    value = model_scorer_node(value)
    return value
