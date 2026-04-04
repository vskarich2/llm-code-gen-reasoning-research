"""Test for l3_state_pipeline: commit and freeze_view are BOTH required.

Invariant:
  1. commit() sets meta.frozen=True and copies pending→stable
     (needed for get_committed_total to return a value)
  2. freeze_view() rebuilds view from stable
     (needed for view-stable consistency: view must reflect committed case_data)

Removing commit() loses the frozen gate.
Removing freeze_view() leaves view built from pending (stage-time),
not from committed stable. The view-stable consistency check catches this.
"""


def test(mod):
    process_batch = getattr(mod, "process_batch", None)
    get_committed_total = getattr(mod, "get_committed_total", None)
    summary_for_display = getattr(mod, "summary_for_display", None)
    project_fn = getattr(mod, "project", None)

    if not all([process_batch, get_committed_total]):
        return False, ["missing process_batch or get_committed_total"]

    try:
        # Entries deliberately in reverse id order.
        # commit() sorts stable by id, so stable order will differ from
        # pending/stage order. freeze_view() must rebuild view from the
        # sorted stable, otherwise view order is stale.
        entries = [{"id": "b", "val": 20}, {"id": "a", "val": 10}]
        st, out = process_batch(entries)
    except Exception as e:
        return False, [f"process_batch raised: {e}"]

    errors = []

    # ── CHECK 1: frozen gate (requires commit) ──
    frozen = st.get("meta", {}).get("frozen", False)
    if not frozen:
        errors.append("meta.frozen is False -- commit() was removed")

    # ── CHECK 2: stable has case_data (requires commit) ──
    stable = st.get("stable", [])
    if not stable:
        errors.append("stable is empty -- commit() did not copy pending to stable")

    # ── CHECK 3: get_committed_total (requires commit) ──
    try:
        total = get_committed_total(st)
    except Exception as e:
        errors.append(f"get_committed_total raised: {e}")
        total = None

    if total is None:
        errors.append("get_committed_total returned None -- frozen gate not set")
    elif total != 30:
        errors.append(f"get_committed_total={total}, expected 30")

    # ── CHECK 4: view-stable consistency (requires freeze_view) ──
    # After the pipeline, view must reflect the committed stable case_data.
    # freeze_view() rebuilds view from stable via project().
    # Without freeze_view, view was built from pending at stage-time,
    # which happens to be the same in the simple case. To detect the
    # difference, we check that view is exactly project(stable).
    view = st.get("view", [])
    if stable and project_fn:
        expected_view = project_fn(stable)
        if view != expected_view:
            errors.append(
                f"view-stable inconsistency: view does not match project(stable). "
                f"freeze_view() may be missing. "
                f"view={view[:2]}, expected={expected_view[:2]}"
            )

    # ── CHECK 5: view has correct projected structure ──
    # Each view entry must have the 'label' key added by project().
    # Without freeze_view, view entries might be raw dicts from stage()
    # if the model changed how stage builds the view.
    if view:
        for i, item in enumerate(view):
            if "label" not in item:
                errors.append(
                    f"view[{i}] missing 'label' key -- view not built via project(). "
                    f"freeze_view() may be missing or project() not applied."
                )
                break
            if "val" not in item:
                errors.append(
                    f"view[{i}] missing 'val' key -- view structure incorrect"
                )
                break

    # ── CHECK 6: summary_for_display consistency ──
    if summary_for_display and not errors:
        try:
            summary = summary_for_display(st)
            if summary.get("count") != len(stable):
                errors.append(
                    f"summary count={summary.get('count')} != stable len={len(stable)} -- "
                    f"view not consistent with committed case_data"
                )
            if summary.get("total_val") != total:
                errors.append(
                    f"summary total_val={summary.get('total_val')} != committed_total={total} -- "
                    f"view-stable mismatch"
                )
        except Exception as e:
            errors.append(f"summary_for_display raised: {e}")

    # ── CHECK 7: freeze_view consistency via incremental batch ──
    # Run a second batch via process_incremental (if available).
    # After the first batch, if freeze_view was NOT called, the view
    # in the state is from stage-time. When process_incremental copies
    # this state and re-stages, the old view propagates as stale.
    # freeze_view ensures the view reflects committed (stable) case_data
    # so the copy_state in process_incremental gets a consistent snapshot.
    process_incremental = getattr(mod, "process_incremental", None)
    if process_incremental and not errors:
        try:
            new_entries = [{"id": "c", "val": 30}]
            st2, out2 = process_incremental(st, new_entries)

            # After incremental: stable should have a+b+c, total=60
            total2 = get_committed_total(st2) if get_committed_total else None
            if total2 is not None and total2 != 60:
                errors.append(
                    f"incremental get_committed_total={total2}, expected 60"
                )

            # View should be consistent with stable after incremental
            stable2 = st2.get("stable", [])
            view2 = st2.get("view", [])
            if stable2 and view2 and project_fn:
                expected_view2 = project_fn(stable2)
                if view2 != expected_view2:
                    errors.append(
                        f"incremental view-stable inconsistency: "
                        f"freeze_view() may be missing. "
                        f"view has {len(view2)} items, expected {len(expected_view2)}"
                    )
        except Exception as e:
            # process_incremental failure is not fatal -- the core invariant
            # is checked above. This is a supplementary consistency check.
            pass

    if errors:
        return False, errors

    return True, ["pipeline commit and freeze_view intact, view-stable consistent, total=30"]
