import random
from store import persist_result, mark_completed, is_completed
from notifier import send_confirmation


def compute(job_id):
    return {"job_id": job_id, "value": 42}


def finalize_job(job_id, result):
    send_confirmation(job_id, result)


def persist(job_id, result):
    persist_result(job_id, result)
    mark_completed(job_id)


def process_job(job_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = compute(job_id)
            finalize_job(job_id, result)
            persist(job_id, result)
            if random.random() < 0.3:
                raise ConnectionError("transient")
            return result
        except ConnectionError:
            continue
    raise RuntimeError("exhausted retries")
