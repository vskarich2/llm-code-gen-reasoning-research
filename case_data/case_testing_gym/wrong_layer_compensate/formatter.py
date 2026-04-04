from parser import parse


def format_roster(raw_text):
    records = parse(raw_text)
    lines = []
    for rec in records:
        name = rec["name"]
        role = rec["role"]
        dept = rec["department"]
        if not name or not role:
            raise ValueError(f"Empty field in record: {rec}")
        lines.append(f"{name} ({role}) - {dept}")
    return "\n".join(lines)


def format_csv(raw_text):
    records = parse(raw_text)
    header = "name,role,department"
    rows = [header]
    for rec in records:
        rows.append(f"{rec['name']},{rec['role']},{rec['department']}")
    return "\n".join(rows)


def get_names(raw_text):
    records = parse(raw_text)
    return [rec["name"] for rec in records]
