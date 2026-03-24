"""Tabular report with headers and rows."""

from data import make_row


class Report:
    """A simple table with column headers and data rows."""

    def __init__(self, headers):
        self.headers = list(headers)
        self.rows = []

    def add_row(self, *values):
        """Add a row of data."""
        self.rows.append(make_row(*values))

    def delete_column(self, index):
        """Remove a column by index from headers and all rows.

        Must remove the header AND the corresponding element
        from every row to keep them aligned.
        """
        # BUG: removes header but does NOT remove from rows
        del self.headers[index]

    def render(self):
        """Render the table as a list of dicts keyed by header."""
        result = []
        for row in self.rows:
            result.append(dict(zip(self.headers, row)))
        return result

    def get_column(self, index):
        """Return all values in a given column."""
        return [row[index] for row in self.rows]

    def column_count(self):
        """Return the number of columns based on headers."""
        return len(self.headers)
