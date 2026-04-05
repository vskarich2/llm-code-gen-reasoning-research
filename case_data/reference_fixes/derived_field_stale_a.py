"""Reference fix: recompute display_name after update."""


class User:
    def __init__(self, first, last):
        self.first = first
        self.last = last
        self.display_name = self._format(first)

    def _format(self, name):
        return name.capitalize()

    def profile(self):
        return {
            "first": self.first,
            "last": self.last,
            "display_name": self.display_name,
        }

    def update_name(self, first, last):
        self.first = first
        self.last = last
        self.display_name = self._format(first)
        return self
