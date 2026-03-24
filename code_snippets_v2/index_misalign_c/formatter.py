"""Table formatter that uses column widths for alignment."""


def format_table(headers, rows, widths):
    """Format a table into aligned string rows.

    Uses widths[i] to pad column i. All three arrays must
    have the same length for correct output.
    """
    lines = []
    header_parts = [h.ljust(widths[i]) for i, h in enumerate(headers)]
    lines.append(" | ".join(header_parts))
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        parts = [str(row[i]).ljust(widths[i]) for i in range(len(headers))]
        lines.append(" | ".join(parts))
    return lines


def recalculate_widths(headers, rows):
    """Recalculate column widths based on actual data.

    Returns a list of widths, one per column.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
    return widths
