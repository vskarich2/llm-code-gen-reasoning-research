_status = "idle"
_data = None


def reset():
    global _status, _data
    _status = "idle"
    _data = None

def load(source):

    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    return _data

def get_status():
    return _status

def get_data():
    return _data

def validate_format(data):
    if data is None:
        return False
    return isinstance(data, list)
