from evaluator_mod import get_fresh_price
from fetcher import prefetch


def compute_value(holdings):
    symbols = list(holdings.keys())
    prefetch(symbols)
    total = 0
    for sym, qty in holdings.items():
        p = get_fresh_price(sym)
        total += p["price"] * qty
    return total


def snapshot(holdings):
    val = compute_value(holdings)
    return {"holdings": holdings, "total_value": val}
