from accounts import transfer, get_total


def move_funds(src, dst, amount):
    total_before = get_total(src, dst)
    transfer(src, dst, amount)
    total_after = get_total(src, dst)
    return {"transferred": amount, "total_before": total_before, "total_after": total_after}
