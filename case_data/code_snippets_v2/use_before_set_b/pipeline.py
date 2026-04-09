from loader import load, get_status, get_data

def reset():
    global _status, _data
    _status = "idle"
    _data = None

def run_pipeline(source):

    load(source)
    status = get_status()
    data = get_data()

    return {
        "status": status,
        "count": len(data) if data else 0,
        "case_data": data,
    }
