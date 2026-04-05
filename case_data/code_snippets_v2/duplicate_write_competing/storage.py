"""Append-only record store. Intentionally allows multiple writes per key."""


class RecordStore:
    def __init__(self):
        self.records = {}

    def write(self, key, value):
        """Append a record. This is append-only by design."""
        if key not in self.records:
            self.records[key] = []
        self.records[key].append(value)

    def read(self, key):
        """Read all records for a key."""
        return self.records.get(key, [])

    def has_record(self, key):
        """Check if any record exists for a key."""
        return key in self.records and len(self.records[key]) > 0
