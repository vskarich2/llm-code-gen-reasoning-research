def is_rate_limited(count, limit):
    return count > limit


def check_and_increment(current_count, limit):
    if is_rate_limited(current_count, limit):
        return True, current_count
    return False, current_count + 1
