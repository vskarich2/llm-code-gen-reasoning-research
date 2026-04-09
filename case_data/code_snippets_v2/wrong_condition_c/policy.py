def is_expired(timestamp, now, window_seconds):
    return (now - timestamp) > window_seconds


def is_under_limit(count, limit):
    return count < limit


def is_exempt(client_id, exempt_list):
    return client_id in exempt_list
