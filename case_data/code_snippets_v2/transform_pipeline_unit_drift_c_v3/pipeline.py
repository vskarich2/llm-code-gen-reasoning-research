from validator import validate
from transform import to_internal
from aggregate import aggregate

def process(xs):
    valid = [x for x in xs if validate(x)]
    transformed = [to_internal(x) for x in valid]
    return aggregate(transformed)
