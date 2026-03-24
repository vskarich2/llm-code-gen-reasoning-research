"""Test for l3_state_pipeline: commit and freeze_view are required.

Invariant: After process_batch, meta.frozen must be True, stable must
contain data, and get_committed_total must return the correct sum.
Removing commit() loses frozen=True. Removing freeze_view() leaves
the view inconsistent with stable.
"""


def test(mod):
    process_batch = getattr(mod, "process_batch", None)
    get_committed_total = getattr(mod, "get_committed_total", None)
    if not all([process_batch, get_committed_total]):
        return False, ["missing process_batch or get_committed_total"]

    try:
        entries = [{"id": "a", "val": 10}, {"id": "b", "val": 20}]
        st, out = process_batch(entries)
    except Exception as e:
        return False, [f"process_batch raised: {e}"]

    errors = []

    # Check frozen gate
    frozen = st.get("meta", {}).get("frozen", False)
    if not frozen:
        errors.append("meta.frozen is False -- commit() was removed")

    # Check stable has data
    stable = st.get("stable", [])
    if not stable:
        errors.append("stable is empty -- commit() did not copy pending to stable")

    # Check get_committed_total
    try:
        total = get_committed_total(st)
    except Exception as e:
        errors.append(f"get_committed_total raised: {e}")
        total = None

    if total is None:
        errors.append("get_committed_total returned None -- frozen gate not set")
    elif total != 30:
        errors.append(f"get_committed_total={total}, expected 30")

    if errors:
        return False, errors

    return True, ["pipeline commit and freeze_view intact, total=30"]
