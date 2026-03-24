"""Report builder with parallel label/value arrays."""

_labels = []
_values = []


def add_entry(label, value, position=None):
    """Add an entry to the report.

    If position is given, insert at that index.
    Otherwise, append to the end.
    """
    if position is not None:
        _labels.insert(position, label)
        # BUG: values always appended instead of inserted at position
        _values.append(value)
    else:
        _labels.append(label)
        _values.append(value)


def get_entry(index):
    """Return (label, value) at the given index."""
    return (_labels[index], _values[index])


def get_all():
    """Return list of (label, value) tuples."""
    return list(zip(_labels, _values))


def count():
    """Return the number of entries."""
    return len(_labels)


def reset():
    """Clear all entries."""
    _labels.clear()
    _values.clear()
