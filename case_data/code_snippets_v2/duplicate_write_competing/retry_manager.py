class RetryManager:
    def __init__(self):
        self.pending = []
        self._handler = None

    def set_handler(self, handler):
        self._handler = handler

    def schedule(self, req_id, payload):

        self.pending.append((req_id, payload))

    def run_pending(self):

        while self.pending:
            req_id, payload = self.pending.pop(0)
            if self._handler:
                self._handler.process_request(req_id, payload)
