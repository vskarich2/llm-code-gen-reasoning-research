"""Tier 1 (T1.1, T1.2) + Tier 2 (T2.4, T2.7): Invariant tests.

T1.1: Reference code passes its own invariants
T1.2: Known broken output fails
T2.4: Mutation perturbation breaks invariants
T2.7: Runtime error during invariant is surfaced
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

import json
from exec_eval import exec_evaluate

BASE = Path(__file__).resolve().parents[1]

def _load_cases():
    return json.loads((BASE / "cases.json").read_text())

def _concat_reference(case):
    parts = []
    for fp in case["code_files"]:
        parts.append((BASE / fp).read_text().strip())
    return "\n\n".join(parts)

def _wrap(code):
    return f"```python\n{code}\n```"


# ── T1.1: Reference code passes own invariants ──────────────

# Cases whose REFERENCE code is intentionally buggy (the trap IS the original code)
EXPECTED_FAIL_CASES = {
    "invariant_partial_fail", "partial_rollback_multi",
    # Diagnostic probe cases — reference code contains the bug by design
    "retry_ack_duplication", "conservation_partial_refund",
    "alias_mutation_shadow", "lock_then_publish_order",
    # Difficulty ladder — all levels contain the bug
    "retry_ack_easy", "retry_ack_medium", "retry_ack_hard",
    "conservation_easy", "conservation_medium", "conservation_hard",
    "alias_easy", "alias_medium", "alias_hard",
    "publish_order_easy", "publish_order_medium", "publish_order_hard",
    # Trivial difficulty — reference code contains the bug
    "retry_ack_trivial", "alias_trivial", "publish_order_trivial",
}

def test_reference_code_passes_own_invariants():
    """For each case: concat reference files → exec_evaluate → passes (except intentionally buggy ones)."""
    cases = _load_cases()
    failures = []
    for case in cases:
        ref = _concat_reference(case)
        result = exec_evaluate(case, ref)
        cid = case["id"]
        if cid in EXPECTED_FAIL_CASES:
            if result["pass"]:
                failures.append(f"{cid}: expected FAIL (buggy reference) but got PASS")
        else:
            if not result["pass"]:
                reasons = "; ".join(result.get("reasons", [])[:2])
                failures.append(f"{cid}: expected PASS but got FAIL ({reasons})")
    assert not failures, "Reference invariant failures:\n" + "\n".join(failures)


# ── T1.2: Known broken output fails ─────────────────────────

def test_known_broken_hidden_dep():
    """Mock baseline for hidden_dep uses refresh_user_snapshot → must fail."""
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "hidden_dep_multihop"][0]
    broken = (
        "_store = {}\n"
        "def cache_put_if_absent(key, value):\n"
        "    if key not in _store: _store[key] = value\n"
        "def refresh_user_snapshot(user):\n"
        "    cache_put_if_absent(f\"user:{user['id']}\", user['name'])\n"
        "def save_user(user):\n"
        "    refresh_user_snapshot(user)\n"
    )
    result = exec_evaluate(case, broken)
    assert not result["pass"], f"broken hidden_dep should fail: {result['reasons']}"


def test_known_broken_state_pipeline():
    """Removing commit() → frozen stays False → must fail."""
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "l3_state_pipeline"][0]
    # Build reference but remove commit(st) line
    ref = _concat_reference(case)
    broken_code = ref.replace("    commit(st)\n", "")
    result = exec_evaluate(case, broken_code)
    assert not result["pass"], f"broken l3 (no commit) should fail: {result['reasons']}"


def test_known_broken_temporal():
    """Moving compute_raw_stats after normalize → wrong stats → must fail."""
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "temporal_semantic_drift"][0]
    broken = (
        "def normalize(data):\n"
        "    m = max(data)\n"
        "    return [x / m for x in data]\n"
        "def clip_negatives(data):\n"
        "    return [max(0, x) for x in data]\n"
        "def smooth(data, window=3):\n"
        "    result = []\n"
        "    for i in range(len(data)):\n"
        "        start = max(0, i - window + 1)\n"
        "        result.append(sum(data[start:i+1]) / (i - start + 1))\n"
        "    return result\n"
        "def compute_raw_stats(data):\n"
        "    return {'raw_mean': sum(data)/len(data), 'raw_max': max(data), 'raw_min': min(data), 'raw_range': max(data)-min(data)}\n"
        "def compute_quality_score(d):\n"
        "    z = sum(1 for x in d if x == 0)\n"
        "    return 1.0 - (z / len(d)) if d else 0.0\n"
        "def summarize_for_display(d):\n"
        "    return {'avg': round(sum(d)/len(d),1), 'peak': round(max(d),1), 'label': 'processed'}\n"
        "def pipeline(data):\n"
        "    cleaned = clip_negatives(normalize(smooth(data)))\n"
        "    raw_stats = compute_raw_stats(cleaned)  # WRONG: should be data\n"
        "    quality = compute_quality_score(cleaned)\n"
        "    return {'raw_stats': raw_stats, 'quality': quality, 'cleaned': cleaned}\n"
    )
    result = exec_evaluate(case, broken)
    assert not result["pass"], f"broken temporal should fail: {result['reasons']}"


# ── T2.4: Mutation perturbation breaks invariant ─────────────

def test_mutation_remove_commit_breaks_state_pipeline():
    """Removing commit(st) from reference code must cause failure."""
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "l3_state_pipeline"][0]
    ref = _concat_reference(case)
    mutated = ref.replace("    commit(st)\n", "    # commit removed\n")
    result = exec_evaluate(case, mutated)
    assert not result["pass"], "removing commit should break frozen gate"


def test_mutation_swap_cache_breaks_hidden_dep():
    """Making sync_user_to_cache use cache_put_if_absent breaks re-save overwrite.

    The invariant test saves user Alice then re-saves as Bob.
    cache_put_if_absent won't overwrite → Bob is lost, cache still shows Alice.
    """
    from exec_eval import load_module_from_code, _strip_local_imports, _load_v2_test
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "hidden_dep_multihop"][0]
    test_fn = _load_v2_test(case)
    assert test_fn is not None, "No test function for hidden_dep_multihop"
    ref = _concat_reference(case)
    # Change sync_user_to_cache to use put_if_absent (won't overwrite)
    mutated = ref.replace(
        "def sync_user_to_cache(user):\n    cache_put(f\"user:{user['id']}\", user[\"name\"])",
        "def sync_user_to_cache(user):\n    cache_put_if_absent(f\"user:{user['id']}\", user[\"name\"])",
    )
    cleaned = _strip_local_imports(mutated)
    mod = load_module_from_code(cleaned, "mut_hidden_dep")
    passed, reasons = test_fn(mod)
    assert not passed, f"put_if_absent should break re-save overwrite: {reasons}"


# ── T2.7: Runtime error during invariant ─────────────────────

def test_runtime_error_during_invariant():
    """Code that raises during invariant test → status=error, not silent pass."""
    cases = _load_cases()
    case = [c for c in cases if c["id"] == "l3_state_pipeline"][0]
    crashing = (
        "def make_state(e): raise RuntimeError('boom')\n"
        "def process_batch(entries):\n"
        "    st = make_state(entries)\n"
        "    return st, {}\n"
    )
    result = exec_evaluate(case, crashing)
    assert not result["pass"]
    ex = result.get("execution", {})
    assert ex.get("status") == "error" or "crash" in str(result.get("reasons", "")).lower() or not ex.get("invariant_pass", True)


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
