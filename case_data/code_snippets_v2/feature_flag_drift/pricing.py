from flags import is_enabled


def compute_price(base, qty):
    if is_enabled("new_pricing"):
        return _v2_price(base, qty)
    return _v1_price(base, qty)


def _v1_price(base, qty):
    return base * qty


def _v2_price(base, qty):
    discount = 0.1 if qty >= 10 else 0
    return base * qty * (1 - discount)


def get_pricing_version():
    return "v2" if is_enabled("new_pricing") else "v1"
