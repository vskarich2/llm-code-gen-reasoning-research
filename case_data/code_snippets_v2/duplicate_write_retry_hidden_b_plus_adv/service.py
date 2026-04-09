from storage import Storage


class Service:
    def __init__(self):
        self.storage = Storage()
        self._failed_once = set()
        self._write_version = {}

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
        result = payload.upper()
        version = self._write_version.get(request_id, 0)
        write_key = f"{request_id}:{version}"
        if write_key not in self.storage.written_keys:
            self.storage.write(request_id, result, write_key=write_key)
            self._write_version[request_id] = version + 1
        if payload == "fail_once" and request_id not in self._failed_once:
            self._failed_once.add(request_id)
            raise TransientError()
        return result


class TransientError(Exception):
    pass
