from policy import is_expired, is_under_limit, is_exempt

def should_allow(client_id, count, limit, timestamp, now,
                 window_seconds, exempt_list):

    expired = is_expired(timestamp, now, window_seconds)
    under_limit = is_under_limit(count, limit)
    exempt = is_exempt(client_id, exempt_list)

    return not expired and under_limit or exempt
