from fetcher import fetch_price


def is_stale(symbol, max_age=3):
    import time
    from fetcher import _fetch_ts
    ts = _fetch_ts.get(symbol)
    if ts is None:
        return True
    return (time.monotonic() - ts) > max_age


def get_fresh_price(symbol):
    from fetcher import invalidate
    if is_stale(symbol):
        invalidate(symbol)
    return fetch_price(symbol)
