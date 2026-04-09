class RecordStore:
    def __init__(self):
        self.records = {}

    def write(self, key, value):

        if key not in self.records:
            self.records[key] = []
        self.records[key].append(value)

    def read(self, key):

        return self.records.get(key, [])

    def has_record(self, key):

        return key in self.records and len(self.records[key]) > 0
