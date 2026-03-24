import time

_cache = {}
_fetch_ts = {}
TTL = 5


def fetch_price(symbol):
    now = time.monotonic()
    if symbol in _cache and (now - _fetch_ts.get(symbol, 0)) < TTL:
        return _cache[symbol]
    price = _remote_get(symbol)
    _cache[symbol] = price
    _fetch_ts[symbol] = now
    return price


def _remote_get(symbol):
    return {"symbol": symbol, "price": 100.0, "ts": time.monotonic()}


def invalidate(symbol):
    _cache.pop(symbol, None)
    _fetch_ts.pop(symbol, None)


def prefetch(symbols):
    for s in symbols:
        fetch_price(s)
