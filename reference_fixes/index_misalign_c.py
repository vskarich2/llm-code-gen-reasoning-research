"""Report with headers, rows, and column widths."""

from data import make_row, validate_table
from formatter import format_table, recalculate_widths


class Report:
    """A table with synchronized headers, rows, and column widths."""

    def __init__(self, headers, default_width=10):
        self.headers = list(headers)
        self.rows = []
        self.column_widths = [default_width] * len(headers)

    def add_row(self, *values):
        """Add a row, padding to match current column count."""
        row = make_row(values, len(self.headers))
        self.rows.append(row)

    def insert_column(self, position, header, default_value=""):
        """Insert a new column at the given position.

        Must update headers, every row, AND column_widths
        to keep all three arrays in sync.
        """
        self.headers.insert(position, header)
        for row in self.rows:
            row.insert(position, default_value)
        # FIX: also insert into column_widths
        self.column_widths.insert(position, len(header))

    def render(self):
        """Render the table using the formatter."""
        return format_table(self.headers, self.rows, self.column_widths)

    def validate(self):
        """Validate internal consistency."""
        return validate_table(self.headers, self.rows, self.column_widths)

    def column_count(self):
        """Return number of columns."""
        return len(self.headers)
