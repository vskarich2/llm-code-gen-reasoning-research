from data import make_row


class Report:

    def __init__(self, headers):
        self.headers = list(headers)
        self.rows = []

    def add_row(self, *values):
        self.rows.append(make_row(*values))

    def delete_column(self, index):
        del self.headers[index]

    def render(self):
        result = []
        for row in self.rows:
            result.append(dict(zip(self.headers, row)))
        return result

    def get_column(self, index):
        return [row[index] for row in self.rows]

    def column_count(self):
        return len(self.headers)
