"""Tests for commit_gate (L3 — but-for causal necessity).

Invariant: ingest produces non-null total, view matches committed, preview does not freeze.
Both commit() and freeze_view() are independently necessary.
"""


def test(mod):
    """Non-diagnostic failures: report symptoms, not missing steps."""
    entries = [{"id": "b", "val": 20}, {"id": "a", "val": 10}]  # intentionally unsorted

    # Test ingest — requires commit (frozen gate)
    result = mod.ingest(entries)
    if result["total"] is None:
        return False, ["committed total is null"]
    if result["total"] != 30:
        return False, [f"committed total={result['total']}, expected 30"]

    # Test consistency — requires freeze_view (view rebuilt from sorted stable)
    verified = mod.ingest_and_verify(entries)
    if not verified["consistent"]:
        return False, ["view and committed data are inconsistent"]

    # Test preview — must not freeze (stage/commit must remain separate)
    preview_result = mod.preview(entries)
    if preview_result["frozen"]:
        return False, ["preview must not freeze state"]
    if len(preview_result["items"]) != 2:
        return False, [f"preview items count={len(preview_result['items'])}, expected 2"]

    return True, ["ingest, consistency, and preview all correct"]
