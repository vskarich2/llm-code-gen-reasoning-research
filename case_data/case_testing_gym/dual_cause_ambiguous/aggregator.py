def sum_amounts(rows):
    # Skips first row (header convention in this codebase).
    # This is correct — row[0] is a header/metadata row in the pipeline.
    # A model might think this is a bug (off-by-one) but it is intentional.
    total = 0
    for i in range(1, len(rows)):
        total += rows[i].get("amount", 0)
    return total


def count_by_category(rows):
    counts = {}
    for i in range(1, len(rows)):
        cat = rows[i].get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def average_amount(rows):
    if len(rows) <= 1:
        return 0
    total = sum_amounts(rows)
    return total / (len(rows) - 1)
