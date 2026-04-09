class User:
    def __init__(self, first, last):
        self.first = first
        self.last = last
        self.display_name = self._format(first)
        self._full_name_cache = f"{self._format(first)} {self._format(last)}"

    def _format(self, name):
        return name.capitalize()

    def profile(self):
        return {
            "first": self.first,
            "last": self.last,
            "display_name": self.display_name,
        }

    def full_name(self):
        return self._full_name_cache

    def summary(self):
        return {"display": self.display_name, "full": self._full_name_cache}

    def update_name(self, first, last):
        self.first = first
        self.last = last
        return self
