_schema = {
    "version": 1,
    "fields": ["id", "name", "email"],
}

_rows = [
    {"id": 1, "name": "Alice", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"},
    {"id": 3, "name": "Carol", "email": "carol@example.com"},
]


def get_schema():
    return dict(_schema)


def get_rows():
    return list(_rows)


def set_schema(new_schema):
    _schema.clear()
    _schema.update(new_schema)


def set_rows(new_rows):
    _rows.clear()
    _rows.extend(new_rows)


def get_version():
    return _schema["version"]


def reset():
    _schema.clear()
    _schema.update({"version": 1, "fields": ["id", "name", "email"]})
    _rows.clear()
    _rows.extend([
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
        {"id": 3, "name": "Carol", "email": "carol@example.com"},
    ])
