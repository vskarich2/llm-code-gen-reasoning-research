"""Request handler — processes incoming requests and writes results."""

from storage import RecordStore


class RequestHandler:
    def __init__(self, store: RecordStore, retry_manager):
        self.store = store
        self.retry_manager = retry_manager
        self._attempt_count = {}

    def process_request(self, req_id, payload):
        """Process a request. On transient failure, delegates to retry manager."""
        self._attempt_count[req_id] = self._attempt_count.get(req_id, 0) + 1

        try:
            result = self._execute(req_id, payload)
            return result
        except TransientError:
            # BUG: first attempt already wrote partial state (via _execute),
            # but we tell the retry manager to re-run the full request.
            # The retry will call process_request again, which calls _execute
            # again, writing a second record.
            self.retry_manager.schedule(req_id, payload)
            return None

    def _execute(self, req_id, payload):
        """Execute the request logic and persist the result."""
        result = payload.upper()

        # Simulate transient failure on first attempt for certain payloads
        if payload.startswith("flaky_") and self._attempt_count.get(req_id, 0) == 1:
            # Write happens BEFORE the failure check — partial commit
            self.store.write(req_id, result)
            raise TransientError(f"transient failure for {req_id}")

        self.store.write(req_id, result)
        return result


class TransientError(Exception):
    pass
