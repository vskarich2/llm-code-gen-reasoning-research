"""Test for ordering_dependency: all items must be processed regardless of order."""


def test(mod):
    # Correct order must work
    log_ok = mod.correct_order()
    if "error" in str(log_ok):
        return False, [f"correct order produced errors: {log_ok}"]
    expected_ok = ["init", "processed:a", "processed:b", "shutdown"]
    if log_ok != expected_ok:
        return False, [f"correct order wrong log: {log_ok}"]

    # Broken order must ALSO produce all processed items
    log_fix = mod.broken_order()
    processed = [e for e in log_fix if e.startswith("processed:")]
    if len(processed) != 2:
        return False, [f"broken order: expected 2 processed items, got {len(processed)}: {log_fix}"]
    if "error" in str(log_fix):
        return False, [f"broken order still has errors: {log_fix}"]

    return True, ["pipeline handles out-of-order execution"]
