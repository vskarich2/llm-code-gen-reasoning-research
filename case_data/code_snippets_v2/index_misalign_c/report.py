

from data import make_row, validate_table
from formatter import format_table, recalculate_widths

class Report:
    def __init__(self, headers, default_width=10):
        self.headers = list(headers)
        self.rows = []
        self.column_widths = [default_width] * len(headers)

    def add_row(self, *values):

        row = make_row(values, len(self.headers))
        self.rows.append(row)

    def insert_column(self, position, header, default_value=""):
        self.headers.insert(position, header)
        for row in self.rows:
            row.insert(position, default_value)

    def render(self):
        return format_table(self.headers, self.rows, self.column_widths)

    def validate(self):
        return validate_table(self.headers, self.rows, self.column_widths)

    def column_count(self):
        return len(self.headers)
