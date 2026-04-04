"""Data storage for tabular reports."""


def make_row(*values):
    """Create a row from positional values."""
    return list(values)


def validate_row(row, expected_cols):
    """Check that a row has the expected number of columns."""
    return len(row) == expected_cols
