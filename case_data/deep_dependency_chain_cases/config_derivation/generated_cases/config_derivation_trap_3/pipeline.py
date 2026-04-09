from data import RAW_DATA
from env import read_env_node
from parser import parse_config
from deriver import derive_settings_node
from service import init_service_node


def run_pipeline(dataset="primary"):
    if "RAW_DATA" in globals():
        data = RAW_DATA[dataset]
    else:
        data = RAW_EVENTS[dataset]
    value = data
    value = read_env_node(value)
    value = parse_config(value)
    value = derive_settings_node(value)
    value = init_service_node(value)
    return value
