

_labels = []
_values = []


def add_entry(label, value, position=None):
    if position is not None:
        _labels.insert(position, label)
        _values.append(value)
    else:
        _labels.append(label)
        _values.append(value)


def get_entry(index):
    return (_labels[index], _values[index])


def get_all():
    return list(zip(_labels, _values))


def count():
    return len(_labels)


def reset():
    _labels.clear()
    _values.clear()
