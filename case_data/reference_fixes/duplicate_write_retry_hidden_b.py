"""Reference fix: cache completed results to make _handle idempotent."""
from storage import Storage


class Service:
    def __init__(self):
        self.storage = Storage()
        self._failed_once = set()
        self._completed_results = {}

    def process(self, request_id, payload):
        return self._retry_wrapper(request_id, payload)

    def _retry_wrapper(self, request_id, payload):
        attempt = 0
        while attempt < 2:
            try:
                return self._handle(request_id, payload)
            except TransientError:
                attempt += 1
        return None

    def _handle(self, request_id, payload):
        if request_id in self._completed_results:
            return self._completed_results[request_id]

        result = payload.upper()
        self.storage.write(request_id, result)
        self._completed_results[request_id] = result

        if payload == "fail_once" and request_id not in self._failed_once:
            self._failed_once.add(request_id)
            raise TransientError()
        return result


class TransientError(Exception):
    pass
