class Storage:
    def __init__(self):
        self.records = []

    def write(self, request_id, result):
        self.records.append({"request_id": request_id, "result": result})

    def get_records(self, request_id):
        return [r for r in self.records if r["request_id"] == request_id]
