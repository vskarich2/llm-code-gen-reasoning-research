_tables = {}


def db_write(table, key, value):
    if table not in _tables:
        _tables[table] = {}
    _tables[table][key] = value


def db_read(table, key):
    return _tables.get(table, {}).get(key)


def db_delete(table, key):
    if table in _tables:
        _tables[table].pop(key, None)
