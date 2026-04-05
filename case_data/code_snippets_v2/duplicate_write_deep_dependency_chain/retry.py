def schedule_retry(queue, request_id, payload):
    queue.enqueue(request_id, payload)
