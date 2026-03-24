def normalize(data):
    m = max(data)
    return [x / m for x in data]


def clip_negatives(data):
    return [max(0, x) for x in data]


def smooth(data, window=3):
    result = []
    for i in range(len(data)):
        start = max(0, i - window + 1)
        result.append(sum(data[start:i + 1]) / (i - start + 1))
    return result
