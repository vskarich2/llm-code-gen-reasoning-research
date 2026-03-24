from container import get_items, add_item, reset


def populate_and_read():
    reset()
    add_item("a")
    add_item("b")
    ref = get_items()
    add_item("c")
    return ref
