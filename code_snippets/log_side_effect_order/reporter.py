from metrics import get_snapshots, get_count


def build_report():
    snaps = get_snapshots()
    return {
        "total_processed": get_count("processed"),
        "total_high": get_count("high_priority"),
        "per_record_snapshots": snaps,
        "n_snapshots": len(snaps),
    }


def verify_consistency():
    snaps = get_snapshots()
    for i, s in enumerate(snaps):
        if s.get("processed", 0) != i + 1:
            return False
    return True
