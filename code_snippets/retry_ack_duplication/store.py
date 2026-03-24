_jobs = {}
_completed = set()


def persist_result(job_id, result):
    _jobs[job_id] = result


def mark_completed(job_id):
    _completed.add(job_id)


def is_completed(job_id):
    return job_id in _completed


def get_result(job_id):
    return _jobs.get(job_id)


def clear():
    _jobs.clear()
    _completed.clear()
