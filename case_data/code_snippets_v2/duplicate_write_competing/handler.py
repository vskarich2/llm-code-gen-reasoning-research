

from storage import RecordStore


class RequestHandler:
    def __init__(self, store: RecordStore, retry_manager):
        self.store = store
        self.retry_manager = retry_manager
        self._attempt_count = {}

    def process_request(self, req_id, payload):
        self._attempt_count[req_id] = self._attempt_count.get(req_id, 0) + 1

        try:
            result = self._execute(req_id, payload)
            return result
        except TransientError:
            self.retry_manager.schedule(req_id, payload)
            return None

    def _execute(self, req_id, payload):
        result = payload.upper()

        if payload.startswith("flaky_") and self._attempt_count.get(req_id, 0) == 1:
            self.store.write(req_id, result)
            raise TransientError(f"transient failure for {req_id}")

        self.store.write(req_id, result)
        return result


class TransientError(Exception):
    pass
