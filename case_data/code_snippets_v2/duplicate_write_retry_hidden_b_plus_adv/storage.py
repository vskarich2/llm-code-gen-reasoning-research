class Storage:
    def __init__(self):
        self.records = []
        self.written_keys = set()

    def write(self, request_id, result, write_key=None):
        key = write_key if write_key is not None else str(request_id)
        self.written_keys.add(key)
        self.records.append({"request_id": request_id, "result": result, "write_key": key})

    def get_records(self, request_id):
        return [r for r in self.records if r["request_id"] == request_id]
