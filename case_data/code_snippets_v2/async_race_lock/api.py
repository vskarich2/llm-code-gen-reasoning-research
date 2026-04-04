from scheduler import run_pipeline, run_verified


def handle_request(items):
    result = run_pipeline(items)
    return result


def handle_verified_request(items):
    return run_verified(items)


def health_check():
    from state import get_counter
    return {"counter": get_counter()}
