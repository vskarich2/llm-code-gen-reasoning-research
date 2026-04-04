"""Adversarial probe definitions for classifier calibration.

38 probes across 7 types (A-G), testing classifier false negative rate.
"""

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

# ── Code modification functions (Types A, B, E) ──────────────


def _mod_a01(files):
    f = "code_snippets_v2/stale_cache_a/catalog.py"
    return files[f].replace(
        "    if product_id in _cache:\n        return _cache[product_id]\n"
        "    product = _db.get(product_id)\n    if product is not None:\n"
        "        _cache[product_id] = dict(product)\n"
        "    return _cache.get(product_id)",
        "    if product_id in _db:\n        return dict(_db[product_id])\n"
        "    return None")


def _mod_a02(files):
    f = "code_snippets_v2/config_shadowing/defaults.py"
    return "import copy\n" + files[f].replace(
        "    return dict(DEFAULTS)", "    return copy.deepcopy(DEFAULTS)")


def _mod_a03(files):
    f = "code_snippets_v2/invariant_partial_fail/transfer_service.py"
    return files[f].replace(
        "    sender.balance -= amount",
        "    if sender.balance < amount:\n"
        "        raise ValueError('insufficient funds')\n"
        "    sender.balance -= amount")


def _mod_b01(files):
    f = "code_snippets_v2/stale_cache_a/catalog.py"
    c = files[f].replace("_cache = {}", "_cache = {}\n_ttl = {}\nimport time")
    return c.replace(
        "        _cache[product_id] = dict(product)",
        "        _cache[product_id] = dict(product)\n"
        "        _ttl[product_id] = time.time() + 60")


def _mod_b02(files):
    return files["code_snippets_v2/lost_update/counter.py"].replace(
        "_value = 0", "_value = 1")


def _mod_b03(files):
    return files["code_snippets_v2/alias_config_c/config.py"].replace(
        "config = DEFAULTS", "config = dict(DEFAULTS)")


def _mod_e01(files):
    return files["code_snippets_v2/stale_cache_a/catalog.py"].replace(
        "    _db[product_id].update(fields)",
        "    _db[product_id] = {**_db[product_id], **fields}")


def _mod_e02(files):
    return files["code_snippets_v2/config_shadowing/defaults.py"].replace(
        'DEFAULTS = {"timeout": 5, "retries": 3}',
        '_ORIG = {"timeout": 5, "retries": 3}\nDEFAULTS = dict(_ORIG)')


def _mod_e03(files):
    return files["code_snippets_v2/lost_update/counter.py"].replace(
        "def run_steps(steps):\n    results = []\n"
        "    for fn, args in steps:\n"
        "        results.append(fn(*args))\n    return results",
        "import threading\n_lock = threading.Lock()\n\n"
        "def run_steps(steps):\n    results = []\n"
        "    with _lock:\n        for fn, args in steps:\n"
        "            results.append(fn(*args))\n    return results")


# ── Synthetic probes (A-E) ────────────────────────────────────
# (id, type, case_id, expected, root_cause, fix_strategy, code_fn)

_SYNTH = [
    ("A-01", "A", "stale_cache_a", "WRONG",
     "get_product reads from _db directly instead of checking _cache, "
     "bypassing the caching layer entirely",
     "Modify get_product to always return from _db when the product exists",
     _mod_a01),
    ("A-02", "A", "config_shadowing", "WRONG",
     "get_defaults returns DEFAULTS by reference, allowing caller mutations "
     "to corrupt global config state",
     "Change get_defaults to return copy.deepcopy(DEFAULTS)",
     _mod_a02),
    ("A-03", "A", "invariant_partial_fail", "WRONG",
     "execute_transfer does not validate that sender has sufficient balance "
     "before performing the debit operation",
     "Add balance validation check before sender.balance -= amount",
     _mod_a03),
    ("B-01", "B", "stale_cache_a", "not_correct",
     "The _cache uses an implicit TTL that expires too quickly, "
     "causing stale reads after the entry times out",
     "Increase the cache TTL or add explicit TTL management",
     _mod_b01),
    ("B-02", "B", "lost_update", "not_correct",
     "Counter initial _value is set to 0 instead of the expected starting "
     "point, causing off-by-one after increments",
     "Change initial _value from 0 to the correct starting value",
     _mod_b02),
    ("B-03", "B", "alias_config_c", "not_correct",
     "DEFAULTS is imported by value into create_config, so changes to "
     "DEFAULTS after import are not reflected in returned config_storage",
     "Wrap DEFAULTS access in dict() to ensure a fresh read on each call",
     _mod_b03),
    ("C-01", "C", "stale_cache_a", "not_correct",
     "There is a case_data consistency issue where stale values are returned "
     "after modification",
     "Update the case_data flow to ensure consistency", None),
    ("C-02", "C", "config_shadowing", "not_correct",
     "The configuration system has a bug where some functions read "
     "wrong values",
     "Fix the functions to read correct values", None),
    ("C-03", "C", "invariant_partial_fail", "not_correct",
     "The transfer has a state management issue causing inconsistency",
     "Refactor to separate concerns and ensure state consistency", None),
    ("D-01", "D", "stale_cache_a", "correct",
     "update_product writes to _db but never invalidates _cache, so "
     "get_product returns stale cached case_data after an update",
     "Add _cache.pop(product_id, None) after _db update in update_product",
     "ref"),
    ("D-02", "D", "config_shadowing", "correct",
     "DEFAULTS timeout is 5 instead of 30; env override masks it on the "
     "request path but run_background_job reads get_defaults() directly",
     "Change DEFAULTS timeout from 5 to 30 in defaults.py", "ref"),
    ("D-03", "D", "invariant_partial_fail", "correct",
     "execute_transfer debits sender then may fail before crediting "
     "receiver; no rollback restores sender.balance on failure",
     "Add try/except around credit with sender.balance += amount on error",
     "ref"),
    ("E-01", "E", "stale_cache_a", "not_correct",
     "After update_product, get_product returns old case_data because "
     "_db.update creates a new dict entry instead of modifying in place",
     "Change _db update to re-assign the entire dict entry",
     _mod_e01),
    ("E-02", "E", "config_shadowing", "not_correct",
     "run_background_job uses wrong timeout because DEFAULTS dict is "
     "mutated by successive get_defaults calls from other modules",
     "Add a copy of DEFAULTS at module load time to prevent mutation",
     _mod_e02),
    ("E-03", "E", "lost_update", "not_correct",
     "Counter reaches wrong final value because run_steps does not lock "
     "the counter between step executions",
     "Add a threading lock around the run_steps execution loop",
     _mod_e03),
]

# ── Type F: Real log-derived probes ───────────────────────────

_FB = "logs/v2_targeted_50trial_canonical/workers"
_FB2 = "logs/v2_anthropic_50trial_v2/workers"

TYPE_F = [
    ("F-01", "cache_invalidation_order", "gpt-4_1-nano__baseline_v2__trial_014__cache_invalidation_order", "not_correct", _FB),
    ("F-02", "cache_invalidation_order", "gpt-4o-mini__baseline_v2__trial_002__cache_invalidation_order", "not_correct", _FB),
    ("F-03", "cache_invalidation_order", "gpt-5_4-mini__leg_reduction_lean_v2__trial_026__cache_invalidation_order", "not_correct", _FB),
    ("F-04", "config_shadowing", "gpt-4_1-nano__baseline_v2__trial_004__config_shadowing", "correct", _FB),
    ("F-05", "config_shadowing", "gpt-4o-mini__baseline_v2__trial_001__config_shadowing", "correct", _FB),
    ("F-06", "config_shadowing", "gpt-5-mini__baseline_v2__trial_001__config_shadowing", "correct", _FB),
    ("F-07", "config_shadowing", "gpt-5_4-mini__leg_reduction_v2__trial_011__config_shadowing", "correct", _FB),
    ("F-08", "hidden_dep_multihop", "gpt-4_1-nano__baseline_v2__trial_012__hidden_dep_multihop", "not_correct", _FB),
    ("F-09", "hidden_dep_multihop", "gpt-4o-mini__leg_reduction_lean_v2__trial_002__hidden_dep_multihop", "not_correct", _FB),
    ("F-10", "hidden_dep_multihop", "gpt-5-mini__baseline_v2__trial_004__hidden_dep_multihop", "not_correct", _FB),
    ("F-11", "hidden_dep_multihop", "gpt-5_4-mini__baseline_v2__trial_001__hidden_dep_multihop", "not_correct", _FB),
    ("F-12", "invariant_partial_fail", "gpt-4_1-nano__baseline_v2__trial_003__invariant_partial_fail", "not_correct", _FB),
    ("F-13", "invariant_partial_fail", "gpt-4o-mini__baseline_v2__trial_002__invariant_partial_fail", "not_correct", _FB),
    ("F-14", "invariant_partial_fail", "gpt-5-mini__baseline_v2__trial_001__invariant_partial_fail", "not_correct", _FB),
    ("F-15", "invariant_partial_fail", "gpt-5_4-mini__baseline_v2__trial_001__invariant_partial_fail", "not_correct", _FB),
    ("F-16", "lost_update", "claude-sonnet-4-20250514__leg_reduction_lean_v2__trial_019__lost_update", "not_correct", _FB2),
    ("F-17", "lost_update", "gpt-4o-mini__baseline_v2__trial_007__lost_update", "not_correct", _FB),
    ("F-18", "lost_update", "gpt-5_4-mini__baseline_v2__trial_008__lost_update", "correct", _FB),
]

# ── Type G: Correct code, wrong reasoning ─────────────────────
# (id, case_id, worker_subdir, log_base, wrong_root_cause, wrong_fix)

TYPE_G = [
    ("G-01", "stale_cache_a",
     "gpt-4_1-nano__baseline_v2__trial_001__stale_cache_a", _FB,
     "get_product creates a shallow copy via dict() that shares nested "
     "mutable objects with _db, causing inconsistent reads after update",
     "Use copy.deepcopy() in get_product instead of dict()"),
    ("G-02", "config_shadowing",
     "gpt-5-mini__baseline_v2__trial_033__config_shadowing", _FB,
     "run_background_job calls get_defaults() instead of get_config(), "
     "bypassing the _OVERRIDES mechanism in env_config",
     "Change run_background_job to call get_config()"),
    ("G-04", "lost_update",
     "gpt-4_1-nano__leg_reduction_lean_v2__trial_012__lost_update", _FB,
     "run_steps executes all steps sequentially without concurrency "
     "control, allowing interleaved reads to see stale counter values",
     "Add a threading lock around the run_steps loop"),
    ("G-05", "alias_config_c",
     "gpt-4_1-nano__baseline_v2__trial_004__alias_config_c", _FB,
     "ConfigMiddleware.__init__ caches create_config() at init time but "
     "reset_defaults() can change DEFAULTS later, leaving stale config",
     "Make ConfigMiddleware read config lazily on each apply_config call"),
    ("G-06", "cache_invalidation_order",
     "gpt-4_1-nano__baseline_v2__trial_021__cache_invalidation_order", _FB,
     "cache_conditional_set has off-by-one in version comparison: initial "
     "version is 0 but get_version returns -1 for missing keys",
     "Change version init in cache_set to -1 to match get_version default"),
]


# ── Public API ─────────────────────────────────────────────────


def get_synthetic_probes(case_by_id):
    """Resolve A-E probes. Returns list of probe dicts."""
    probes = []
    for pid, ptype, cid, expected, rc, fs, code_fn in _SYNTH:
        case = case_by_id[cid]
        files = dict(case["code_files_contents"])
        if code_fn is None:
            code = "\n\n".join(files.values())
        elif code_fn == "ref":
            code = (PROJECT / "reference_fixes" / f"{cid}.py").read_text()
        else:
            code = code_fn(files)
        probes.append({"id": pid, "type": ptype, "case_id": cid,
                        "expected": expected, "root_cause": rc,
                        "fix_strategy": fs, "code": code})
    return probes


def _load_from_worker(wdir_name, base, cid):
    """Extract reasoning + code from a worker directory."""
    worker = PROJECT / base / wdir_name / "attempt_001"
    call_file = worker / "calls" / "000001.json"
    if not call_file.exists():
        return None, None, ""

    raw = json.loads(call_file.read_text()).get("response_raw", "")
    from core.pipeline.parsing import parse_v2_execution
    cond = "baseline_v2"
    if "leg_reduction_lean" in wdir_name:
        cond = "leg_reduction_lean_v2"
    elif "leg_reduction" in wdir_name:
        cond = "leg_reduction_v2"
    parsed = parse_v2_execution(raw, cond)

    rc = parsed.full_json.get("root_cause", "") if parsed.full_json else ""
    fs = parsed.full_json.get("fix_strategy", "") if parsed.full_json else ""

    code = ""
    if parsed.files_dict:
        cases = json.loads((PROJECT / "cases_v2.json").read_text())
        case = next(c for c in cases if c["id"] == cid)
        mf = {p: (PROJECT / p).read_text() for p in case["code_files"]}
        from core.pipeline.reconstructor import reconstruct_strict
        recon = reconstruct_strict(list(mf.keys()), mf, parsed.files_dict)
        if recon.status == "SUCCESS":
            ch = [recon.files[p] for p in case["code_files"]
                  if p in recon.changed_files]
            code = "\n\n".join(ch) if ch else "\n\n".join(
                recon.files.values())
    return rc, fs, code


def get_type_f_probes():
    """Load Type F probes from worker directories."""
    probes = []
    for pid, cid, wdir, expected, base in TYPE_F:
        rc, fs, code = _load_from_worker(wdir, base, cid)
        if rc is None:
            print(f"  WARN: {pid} worker missing, skipped", flush=True)
            continue
        probes.append({"id": pid, "type": "F", "case_id": cid,
                        "expected": expected, "root_cause": rc,
                        "fix_strategy": fs, "code": code})
    return probes


def get_type_g_probes(case_by_id):
    """Load Type G: correct code from logs + wrong reasoning."""
    probes = []
    for pid, cid, wdir, base, wrong_rc, wrong_fs in TYPE_G:
        _, _, code = _load_from_worker(wdir, base, cid)
        if not code:
            print(f"  WARN: {pid} no code extracted, skipped", flush=True)
            continue
        probes.append({"id": pid, "type": "G", "case_id": cid,
                        "expected": "not_correct", "root_cause": wrong_rc,
                        "fix_strategy": wrong_fs, "code": code})
    return probes
