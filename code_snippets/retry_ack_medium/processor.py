from store import send, mark_done, is_done


def process_job(job_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            send(job_id)
            mark_done(job_id)
            if attempt == 0:
                raise ConnectionError("transient")
            return {"job_id": job_id, "value": 42}
        except ConnectionError:
            continue
    raise RuntimeError("exhausted retries")
