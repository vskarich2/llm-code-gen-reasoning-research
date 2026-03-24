_data = {"items": []}


def get_items():
    return _data["items"]


def add_item(item):
    _data["items"].append(item)


def reset():
    _data["items"] = []
