from data_loader import fetch_page, total_rows
from aggregator import sum_amounts, count_by_category


def build_page_report(page_offset=0, page_size=3):
    rows = fetch_page(offset=page_offset, limit=page_size)
    total = sum_amounts(rows)
    counts = count_by_category(rows)
    return {
        "rows_fetched": len(rows),
        "total_amount": total,
        "category_counts": counts,
        "page_offset": page_offset,
        "page_size": page_size,
    }


def build_full_report():
    all_rows = []
    offset = 0
    page_size = 3
    n = total_rows()
    while offset < n:
        page = fetch_page(offset=offset, limit=page_size)
        if not page:
            break
        all_rows.extend(page)
        offset += page_size
    total = sum_amounts([{"amount": 0}] + all_rows)
    counts = count_by_category([{"category": "_header"}] + all_rows)
    return {
        "rows_fetched": len(all_rows),
        "total_amount": total,
        "category_counts": counts,
    }
