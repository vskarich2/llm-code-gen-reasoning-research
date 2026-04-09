_sent = []

def reset():
    global _sent
    _sent = []

def send(msg):
    _sent.append(msg)
    return True

def retry_send(msg, max_retries=2):
    for attempt in range(max_retries):
        result = send(msg)
        if not result:
            continue
    return True

def get_sent():
    return list(_sent)

def clear_log():
    pass
