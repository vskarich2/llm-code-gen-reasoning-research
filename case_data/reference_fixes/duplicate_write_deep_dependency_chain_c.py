"""Reference fix: add idempotency guard to service.process and schedule_retry."""
from storage import Storage


class Service:
    def __init__(self, queue):
        self.queue = queue
        self.storage = Storage()
        self.completed = set()

    def process(self, request_id, payload):
        if request_id in self.completed:
            return None
        try:
            result = self._handle(request_id, payload)
            self.completed.add(request_id)
            return result
        except TransientError:
            schedule_retry(self.queue, request_id, payload, self.completed)
            return None

    def _handle(self, request_id, payload):
        if payload == "fail_once":
            raise TransientError()
        result = payload.upper()
        self.storage.write(request_id, result)
        return result


class TransientError(Exception):
    pass


def schedule_retry(queue, request_id, payload, completed):
    if request_id in completed:
        return
    queue.enqueue(request_id, payload)
