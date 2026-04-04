_index = {}


def reindex(user_id, name):
    _index[user_id] = name


def lookup(user_id):
    return _index.get(user_id)


def search(query):
    results = []
    for uid, name in _index.items():
        if query.lower() in name.lower():
            results.append(uid)
    return results


def remove(user_id):
    _index.pop(user_id, None)


def reset():
    _index.clear()
