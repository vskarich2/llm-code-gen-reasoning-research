_completed = set()
_sent = []


def send(job_id):
    _sent.append(job_id)


def mark_done(job_id):
    _completed.add(job_id)


def is_done(job_id):
    return job_id in _completed


def get_sent():
    return list(_sent)


def clear():
    _sent.clear()
    _completed.clear()
