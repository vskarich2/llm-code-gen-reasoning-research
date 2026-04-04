_source_rows = [
    {"id": 1, "category": "A", "amount": 100},
    {"id": 2, "category": "B", "amount": 200},
    {"id": 3, "category": "A", "amount": 150},
    {"id": 4, "category": "C", "amount": 300},
    {"id": 5, "category": "B", "amount": 250},
    {"id": 6, "category": "A", "amount": 175},
    {"id": 7, "category": "C", "amount": 125},
    {"id": 8, "category": "B", "amount": 225},
]


def fetch_page(offset=0, limit=3):
    # BUG: off-by-one — returns limit-1 rows instead of limit
    # Should be rows[offset:offset+limit], but uses offset+limit-1
    return _source_rows[offset:offset + limit - 1]


def total_rows():
    return len(_source_rows)


def fetch_all():
    return list(_source_rows)


def reset():
    pass
