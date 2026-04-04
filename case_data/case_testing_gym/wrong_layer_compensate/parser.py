def parse(raw_text):
    lines = raw_text.strip().split("\n")
    records = []
    for line in lines:
        parts = line.split(",")
        if len(parts) >= 3:
            # BUG: does not strip whitespace from fields
            records.append({
                "name": parts[0],
                "role": parts[1],
                "department": parts[2],
            })
    return records


def parse_single(raw_line):
    parts = raw_line.split(",")
    if len(parts) < 3:
        return None
    return {
        "name": parts[0],
        "role": parts[1],
        "department": parts[2],
    }


def count_fields(raw_text):
    records = parse(raw_text)
    return len(records)
