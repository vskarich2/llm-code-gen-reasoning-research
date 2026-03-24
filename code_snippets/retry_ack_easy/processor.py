_sent = []
_completed = set()


def get_sent():
    return list(_sent)


def is_completed(job_id):
    return job_id in _completed


def clear():
    _sent.clear()
    _completed.clear()


def process_job(job_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            _sent.append(job_id)
            _completed.add(job_id)
            if attempt == 0:
                raise ConnectionError("transient")
            return {"job_id": job_id, "value": 42}
        except ConnectionError:
            continue
    raise RuntimeError("exhausted retries")
