from retry import schedule_retry
from storage import Storage


class Service:
    def __init__(self, queue):
        self.queue = queue
        self.storage = Storage()

    def process(self, request_id, payload):
        try:
            result = self._handle(request_id, payload)
            return result
        except TransientError:
            schedule_retry(self.queue, request_id, payload)
            return None

    def _handle(self, request_id, payload):
        if payload == "fail_once":
            raise TransientError()
        result = payload.upper()
        self.storage.write(request_id, result)
        return result


class TransientError(Exception):
    pass
