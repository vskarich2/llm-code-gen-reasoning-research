"""Tests for index_misalign family (partial_state_update).

Invariant: Parallel data structures (labels/values, headers/rows,
           headers/rows/widths) must stay synchronized after mutations.
"""


def test_a(mod):
    """Level A: insert at position misaligns labels and values."""
    # Reset module state
    if hasattr(mod, "_labels"):
        mod._labels.clear()
    if hasattr(mod, "_values"):
        mod._values.clear()

    add = getattr(mod, "add_entry", None)
    get = getattr(mod, "get_entry", None)
    if add is None:
        return False, ["add_entry not found"]
    if get is None:
        return False, ["get_entry not found"]

    try:
        add("alpha", 10)
        add("beta", 20)
        # Insert at position 0 — should shift everything right
        add("gamma", 30, position=0)
    except Exception as e:
        return False, [f"add_entry raised: {e}"]

    try:
        entry = get(0)
    except Exception as e:
        return False, [f"get_entry raised: {e}"]

    if entry != ("gamma", 30):
        return False, [
            f"get_entry(0) returned {entry}, expected ('gamma', 30). "
            f"After inserting at position 0, label and value are misaligned."
        ]

    # Also check position 1 to confirm alignment
    try:
        entry1 = get(1)
    except Exception as e:
        return False, [f"get_entry(1) raised: {e}"]

    if entry1 != ("alpha", 10):
        return False, [
            f"get_entry(1) returned {entry1}, expected ('alpha', 10)."
        ]

    return True, ["insert at position correctly aligns labels and values"]


def test_b(mod):
    """Level B: delete_column removes header but not row data."""
    Report = getattr(mod, "Report", None)
    if Report is None:
        return False, ["Report class not found"]

    try:
        r = Report(["name", "age", "city"])
        r.add_row("Alice", 30, "NYC")
        r.add_row("Bob", 25, "LA")
        r.delete_column(1)  # Remove "age" column
    except Exception as e:
        return False, [f"Report operations raised: {e}"]

    try:
        rendered = r.render()
    except Exception as e:
        return False, [f"render raised: {e}"]

    # After deleting "age", render should produce dicts with "name" and "city"
    if not rendered:
        return False, ["render returned empty result"]

    first = rendered[0]
    if first.get("name") != "Alice":
        return False, [
            f"After deleting 'age' column, first row 'name' is "
            f"{first.get('name')!r}, expected 'Alice'. Row data misaligned "
            f"with headers. Full render: {rendered}"
        ]

    if first.get("city") != "NYC":
        return False, [
            f"After deleting 'age' column, first row 'city' is "
            f"{first.get('city')!r}, expected 'NYC'. Row data misaligned "
            f"with headers. Full render: {rendered}"
        ]

    return True, ["delete_column correctly removes from both headers and rows"]


def test_c(mod):
    """Level C: insert_column updates headers and rows but not widths."""
    Report = getattr(mod, "Report", None)
    if Report is None:
        return False, ["Report class not found"]

    try:
        r = Report(["name", "score"], default_width=10)
        r.add_row("Alice", 95)
        r.add_row("Bob", 87)
        r.insert_column(1, "grade", "A")
    except Exception as e:
        return False, [f"Report operations raised: {e}"]

    # Check internal consistency via validate()
    validate = getattr(r, "validate", None)
    if validate:
        try:
            ok, msg = validate()
        except Exception as e:
            return False, [f"validate raised: {e}"]
        if not ok:
            return False, [
                f"validate() failed after insert_column: {msg}. "
                f"headers/rows/widths are out of sync."
            ]

    # Also verify render doesn't crash (widths must match headers)
    try:
        lines = r.render()
    except (IndexError, Exception) as e:
        return False, [
            f"render() failed after insert_column: {e}. "
            f"column_widths likely not updated."
        ]

    if not lines:
        return False, ["render returned empty result"]

    return True, ["insert_column correctly updates headers, rows, and widths"]
