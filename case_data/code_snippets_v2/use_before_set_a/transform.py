_last_result = []

def transform(data):
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    return _last_result


def format_output(transformed):
    return [str(x) for x in transformed]
