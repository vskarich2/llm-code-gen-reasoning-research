"""Data utilities for tabular reports."""


def make_row(values, num_cols):
    """Create a row with exactly num_cols elements, padding if needed."""
    row = list(values)[:num_cols]
    while len(row) < num_cols:
        row.append(None)
    return row


def validate_table(headers, rows, widths):
    """Check structural consistency of table components."""
    if len(headers) != len(widths):
        return False, "header/width count mismatch"
    for i, row in enumerate(rows):
        if len(row) != len(headers):
            return False, f"row {i} has {len(row)} cols, expected {len(headers)}"
    return True, "ok"
