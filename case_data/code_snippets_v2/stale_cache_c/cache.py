_local = {}
_shared = {}

def get_local(key):
    return _local.get(key)

def put_local(key, value):
    _local[key] = value

def invalidate_local(key):
    _local.pop(key, None)

def get_shared(key):
    return _shared.get(key)

def put_shared(key, value):
    _shared[key] = value

def invalidate_shared(key):
    _shared.pop(key, None)

def clear_all():
    _local.clear()
    _shared.clear()
