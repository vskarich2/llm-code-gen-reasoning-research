class Storage:
    def __init__(self):
        self.data = {}

    def write(self, key, value):
        self.data.setdefault(key, []).append(value)

    def read(self, key):
        return self.data.get(key, [])
