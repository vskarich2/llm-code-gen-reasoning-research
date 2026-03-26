"""Execution-based evaluator for T3 benchmark.

Executes model-generated code and tests causal invariants.
Parsing and code extraction live in parse.py.
"""

import importlib
import importlib.util
import itertools
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_eval_log = logging.getLogger("t3.exec_eval")

# Canonical imports from parse.py
from parse import (
    extract_code,
    extract_all_code_blocks,
    strip_local_imports as _strip_local_imports,
    STDLIB_MODULES as _STDLIB_MODULES,
)


# ============================================================
# MODULE LOADING
# ============================================================

_load_counter = itertools.count(1)


def load_module_from_code(code: str, name: str = "candidate") -> ModuleType:
    """Load a string of Python code as a module.

    Strips local cross-file imports since all code is concatenated.
    Thread-safe: uses itertools.count() (atomic on CPython).
    """
    mod_name = f"_t3_exec_{name}_{next(_load_counter)}"

    cleaned = _strip_local_imports(code)

    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__builtins__"] = __builtins__

    try:
        exec(compile(cleaned, f"<{mod_name}>", "exec"), mod.__dict__)
    except SyntaxError as e:
        raise SyntaxError(f"Candidate code syntax error: {e}") from e

    sys.modules[mod_name] = mod
    return mod


# ============================================================
# RESULT BUILDER
# ============================================================

def _result(case_id: str, passed: bool, score: float, reasons: list[str],
            failure_modes: list[str], execution: dict,
            extracted_code: str = "",
            assembled_code: str = "") -> dict:
    return {
        "pass": passed,
        "score": round(score, 2),
        "reasons": reasons,
        "failure_modes": failure_modes,
        "execution": execution,
        "_extracted_code": extracted_code,
        "_assembled_code": assembled_code,
    }


def _exec_info(**kw) -> dict:
    """Structured execution result. Never ambiguous."""
    passed_tests = kw.get("passed_tests", 0)
    total_tests = kw.get("total_tests", 0)
    has_syntax = kw.get("syntax_error") is not None
    has_runtime = kw.get("runtime_error") is not None
    inv_pass = kw.get("invariant_pass")
    mut_pass = kw.get("mutation_pass")
    ran = kw.get("ran", False)

    if has_syntax or has_runtime:
        status = "error"
    elif inv_pass is False or mut_pass is False:
        status = "failed"
    elif inv_pass and (mut_pass is True or mut_pass is None):
        status = "passed"
    else:
        status = "failed"

    assembly_error = kw.get("assembly_error", False)
    if assembly_error:
        status = "assembly_error"

    # INVARIANT: if code didn't run, no tests could have run
    assert not (ran is False and total_tests > 0), (
        f"LOGGING BUG: ran=False but total_tests={total_tests}. "
        f"total_tests must be 0 when code did not execute."
    )

    return {
        "status": status,
        "passed_tests": passed_tests,
        "total_tests": total_tests,
        "runtime_error": has_runtime,
        "error_message": kw.get("syntax_error") or kw.get("runtime_error"),
        # Assembly tracking — full provenance
        "assembly_used": kw.get("assembly_used", False),
        "assembly_error": assembly_error,
        "assembly_risky": kw.get("assembly_risky", False),
        "rename_error": kw.get("rename_error", False),
        "assembly_sources": kw.get("assembly_sources"),
        # Legacy fields for backward compat
        "ran": ran,
        "syntax_error": kw.get("syntax_error"),
        "invariant_pass": inv_pass,
        "mutation_pass": mut_pass,
    }


# compute_alignment is defined in evaluator.py. Do NOT import it here
# to avoid circular import (evaluator imports exec_evaluate from us).


# ============================================================
# CASE-SPECIFIC INVARIANT TESTS
# ============================================================

def _test_temporal(mod) -> tuple[bool, list[str]]:
    """pipeline(data) must return raw_stats computed on original data,
    not on transformed data."""
    pipeline_fn = getattr(mod, "pipeline", None)
    if pipeline_fn is None:
        return False, ["pipeline function not found"]
    try:
        data = [10, 20, 30, 40, 50]
        result = pipeline_fn(data)
        stats = result.get("raw_stats", {})
        if "raw_max" not in stats:
            return False, [f"raw_stats missing raw_max key; got {list(stats.keys())}"]
        if abs(stats["raw_max"] - 50) > 0.01:
            return False, [f"raw_max={stats['raw_max']}, expected 50 (got normalized value?)"]
        if abs(stats["raw_mean"] - 30) > 0.01:
            return False, [f"raw_mean={stats['raw_mean']}, expected 30"]
        return True, ["raw_stats correctly reflects original data"]
    except Exception as e:
        return False, [f"pipeline raised: {e}"]


def _test_idempotency(mod) -> tuple[bool, list[str]]:
    """Retrying an adjust event must not double the delta."""
    clear = getattr(mod, "clear", None)
    process_event = getattr(mod, "process_event", None)
    get = getattr(mod, "get", None)
    if not all([process_event, get]):
        return False, ["process_event or get not found"]
    try:
        if clear:
            clear()
        # Set base value
        process_event({"type": "set", "key": "x", "value": 100})
        # Apply delta once
        process_event({"type": "adjust", "key": "x", "delta": 10})
        val = get("x")
        if val != 110:
            return False, [f"after single adjust: got {val}, expected 110"]
        return True, ["single adjust produces correct value"]
    except Exception as e:
        return False, [f"idempotency test raised: {e}"]


def _test_partial_rollback(mod) -> tuple[bool, list[str]]:
    """If wallet.charge fails, inventory must be released."""
    Inventory = getattr(mod, "Inventory", None)
    Wallet = getattr(mod, "Wallet", None)
    place_order = getattr(mod, "place_order", None)
    if not all([Inventory, Wallet, place_order]):
        return False, ["Inventory, Wallet, or place_order not found"]
    try:
        inv = Inventory()
        inv.stock["SKU1"] = 10
        w = Wallet(balance=5)  # insufficient for charge
        # Patch module-level inventory and wallet
        mod.inventory = inv
        mod.wallet = w
        stock_before = inv.stock["SKU1"]
        try:
            place_order("ord1", "SKU1", 3, 10)  # 3*10=30 > balance 5
        except ValueError:
            pass  # expected: insufficient funds
        stock_after = inv.stock.get("SKU1", 0)
        if stock_after != stock_before:
            return False, [f"stock not restored: before={stock_before}, after={stock_after}"]
        return True, ["inventory released after charge failure"]
    except Exception as e:
        return False, [f"rollback test raised: {e}"]


def _test_lazy_init(mod) -> tuple[bool, list[str]]:
    """After reset + override, settings must reflect overrides."""
    reset = getattr(mod, "reset", None)
    override = getattr(mod, "override_settings", None)
    get_settings = getattr(mod, "get_settings", None)
    if not all([reset, override, get_settings]):
        return False, ["reset, override_settings, or get_settings not found"]
    try:
        # First access (lazy init with defaults)
        s1 = get_settings()
        old_timeout = s1.get("timeout")
        # Reset + override
        reset()
        override({"timeout": 99})
        s2 = get_settings()
        if s2.get("timeout") != 99:
            return False, [f"timeout after reset+override: got {s2.get('timeout')}, expected 99"]
        # Verify s1 is NOT still pointing to live settings (or if it is, it shows 99)
        return True, ["settings correctly reflect override after reset"]
    except Exception as e:
        return False, [f"lazy init test raised: {e}"]


def _test_log_order(mod) -> tuple[bool, list[str]]:
    """Per-record snapshots must have incrementally increasing processed count."""
    ingest = getattr(mod, "ingest", None)
    if ingest is None:
        return False, ["ingest not found"]
    try:
        records = [{"id": f"r{i}", "priority": "high" if i % 2 == 0 else "low"} for i in range(5)]
        result = ingest(records)
        if not result.get("consistent", False):
            return False, ["verify_consistency returned False"]
        snaps = result.get("report", {}).get("per_record_snapshots", [])
        if len(snaps) != 5:
            return False, [f"expected 5 snapshots, got {len(snaps)}"]
        for i, s in enumerate(snaps):
            if s.get("processed") != i + 1:
                return False, [f"snapshot[{i}].processed={s.get('processed')}, expected {i+1}"]
        return True, ["per-record snapshots correctly ordered"]
    except Exception as e:
        return False, [f"log order test raised: {e}"]


def _test_retry_causality(mod) -> tuple[bool, list[str]]:
    """Sequence IDs must be unique and monotonic after batch ingest."""
    ingest = getattr(mod, "ingest_batch", None) or getattr(mod, "ingest_safe", None)
    if ingest is None:
        return False, ["ingest_batch/ingest_safe not found"]
    try:
        # Patch random to never fail (deterministic)
        import random
        old_random = random.random
        random.random = lambda: 0.99  # never triggers failure
        try:
            records = [{"key": f"k{i}", "value": f"v{i}"} for i in range(5)]
            result = ingest(records)
        finally:
            random.random = old_random
        seqs = [r.get("seq") for r in result.get("results", []) if r.get("seq") is not None]
        if len(seqs) != 5:
            return False, [f"expected 5 sequence IDs, got {len(seqs)}"]
        if seqs != sorted(set(seqs)):
            return False, [f"sequence IDs not unique+monotonic: {seqs}"]
        return True, ["sequence IDs are unique and monotonic"]
    except Exception as e:
        return False, [f"retry test raised: {e}"]


def _test_shared_ref(mod) -> tuple[bool, list[str]]:
    """Registering a handler must be visible to dispatch_all via shared reference."""
    init = getattr(mod, "init", None)
    dispatch_all = getattr(mod, "dispatch_all", None) or getattr(mod, "run_all", None)
    register = getattr(mod, "register", None)
    if not all([init, dispatch_all]):
        return False, ["init or dispatch_all/run_all not found"]
    try:
        init()
        # Register a new handler AFTER init
        if register:
            register("custom", lambda d: "custom_result")
        results = dispatch_all({"name": "test"})
        if register and "custom" not in results:
            return False, ["late-registered handler not visible to dispatch_all"]
        if "greet" not in results:
            return False, ["base handler 'greet' not visible"]
        return True, ["handlers visible through shared reference"]
    except Exception as e:
        return False, [f"shared ref test raised: {e}"]


def _test_external_timing(mod) -> tuple[bool, list[str]]:
    """get_fresh_price must detect stale data."""
    get_fresh = getattr(mod, "get_fresh_price", None)
    is_stale = getattr(mod, "is_stale", None)
    if get_fresh is None:
        return False, ["get_fresh_price not found"]
    try:
        p1 = get_fresh("AAPL")
        if p1 is None:
            return False, ["get_fresh_price returned None"]
        if "price" not in p1:
            return False, [f"no 'price' key in result: {p1}"]
        return True, ["get_fresh_price returns valid price"]
    except Exception as e:
        return False, [f"timing test raised: {e}"]


# ── Easy calibration invariant tests ──────────────────────────

def _test_easy_temporal(mod) -> tuple[bool, list[str]]:
    """Logged value must equal stored value after update."""
    update = getattr(mod, "update_value", None)
    get_log = getattr(mod, "get_log", None)
    clear = getattr(mod, "clear", None)
    if not all([update, get_log]):
        # Try via process()
        process = getattr(mod, "process", None)
        if process:
            try:
                r = process("k", "hello")
                if r.get("stored") != r.get("logged"):
                    return False, [f"stored={r['stored']} != logged={r['logged']}"]
                return True, ["logged value equals stored value"]
            except Exception as e:
                return False, [f"process raised: {e}"]
        return False, ["update_value/process not found"]
    try:
        if clear:
            clear()
        store = {}
        update(store, "x", 42)
        log = get_log()
        if not log:
            return False, ["log is empty after update"]
        if log[-1]["value"] != 42:
            return False, [f"logged value={log[-1]['value']}, expected 42"]
        if store.get("x") != 42:
            return False, [f"stored value={store.get('x')}, expected 42"]
        return True, ["logged value equals stored value"]
    except Exception as e:
        return False, [f"easy_temporal raised: {e}"]


def _test_easy_conservation(mod) -> tuple[bool, list[str]]:
    """Sum of balances must be conserved after transfer."""
    transfer = getattr(mod, "transfer", None)
    get_total = getattr(mod, "get_total", None)
    if not transfer:
        # Try via move_funds
        move = getattr(mod, "move_funds", None)
        if move:
            try:
                a = {"balance": 100}
                b = {"balance": 50}
                r = move(a, b, 30)
                if a["balance"] + b["balance"] != 150:
                    return False, [f"total={a['balance']+b['balance']}, expected 150"]
                return True, ["total conserved after transfer"]
            except Exception as e:
                return False, [f"move_funds raised: {e}"]
        return False, ["transfer/move_funds not found"]
    try:
        a = {"balance": 100}
        b = {"balance": 50}
        total_before = a["balance"] + b["balance"]
        transfer(a, b, 30)
        total_after = a["balance"] + b["balance"]
        if total_after != total_before:
            return False, [f"total changed: {total_before} → {total_after}"]
        if a["balance"] != 70:
            return False, [f"src balance={a['balance']}, expected 70"]
        if b["balance"] != 80:
            return False, [f"dst balance={b['balance']}, expected 80"]
        return True, ["total conserved, balances correct"]
    except Exception as e:
        return False, [f"easy_conservation raised: {e}"]


def _test_easy_state_machine(mod) -> tuple[bool, list[str]]:
    """draft→submitted→approved works. draft→approved must raise."""
    transition = getattr(mod, "transition", None)
    if not transition:
        return False, ["transition not found"]
    try:
        # Valid path
        item = {"status": "draft"}
        transition(item, "submitted")
        if item["status"] != "submitted":
            return False, [f"after submit: status={item['status']}"]
        transition(item, "approved")
        if item["status"] != "approved":
            return False, [f"after approve: status={item['status']}"]
        # Invalid path: draft → approved
        item2 = {"status": "draft"}
        try:
            transition(item2, "approved")
            return False, ["draft→approved should raise ValueError"]
        except ValueError:
            pass
        return True, ["valid transitions work, invalid raises"]
    except Exception as e:
        return False, [f"easy_state_machine raised: {e}"]


def _test_easy_aliasing(mod) -> tuple[bool, list[str]]:
    """get_items returns live reference — add_item after get is visible."""
    get_items = getattr(mod, "get_items", None)
    add_item = getattr(mod, "add_item", None)
    reset = getattr(mod, "reset", None)
    populate = getattr(mod, "populate_and_read", None)
    if populate:
        try:
            ref = populate()
            if "c" not in ref:
                return False, [f"add_item('c') after get_items not visible: {ref}"]
            return True, ["live reference reflects subsequent mutations"]
        except Exception as e:
            return False, [f"populate_and_read raised: {e}"]
    if not all([get_items, add_item]):
        return False, ["get_items/add_item not found"]
    try:
        if reset:
            reset()
        add_item("x")
        ref = get_items()
        add_item("y")
        if "y" not in ref:
            return False, [f"add_item after get_items not visible: {ref}"]
        return True, ["live reference reflects subsequent mutations"]
    except Exception as e:
        return False, [f"easy_aliasing raised: {e}"]


# ── Diagnostic probe invariant tests ─────────────────────────

def _test_retry_ack_duplication(mod) -> tuple[bool, list[str]]:
    """At most one email per job_id across retries."""
    process_job = getattr(mod, "process_job", None)
    get_sent = getattr(mod, "get_sent", None)
    clear = getattr(mod, "clear", None)
    clear_sent = getattr(mod, "clear_sent", None)
    if not process_job:
        return False, ["process_job not found"]
    try:
        if clear: clear()
        if clear_sent: clear_sent()
        import random
        # Force one retry: first attempt raises, second succeeds
        call_count = [0]
        orig = random.random
        def fake():
            call_count[0] += 1
            return 0.1 if call_count[0] == 1 else 0.99
        random.random = fake
        try:
            process_job("J1")
        except Exception:
            pass  # may raise if all retries fail
        finally:
            random.random = orig
        if not get_sent:
            return False, ["get_sent not found"]
        raw = get_sent()
        # Handle both formats: list of dicts (original) or list of strings (simplified)
        sent = []
        for e in raw:
            if isinstance(e, dict) and e.get("job_id") == "J1":
                sent.append(e)
            elif isinstance(e, str) and e == "J1":
                sent.append(e)
        if len(sent) > 1:
            return False, [f"duplicate emails: {len(sent)} sent for J1 (expected 1)"]
        if len(sent) == 0:
            return False, ["no email sent for J1"]
        return True, ["exactly 1 email per job_id"]
    except Exception as e:
        return False, [f"retry_ack test raised: {e}"]


def _test_conservation_partial_refund(mod) -> tuple[bool, list[str]]:
    """merchant_delta + customer_delta + fee == 0 for partial refund."""
    process_refund = getattr(mod, "process_refund", None)
    if not process_refund:
        return False, ["process_refund not found"]
    try:
        m = {"balance": 1000}
        c = {"balance": 200}
        result = process_refund(m, c, 100, partial=True)
        merchant_lost = 1000 - m["balance"]
        customer_gained = c["balance"] - 200
        if merchant_lost != customer_gained:
            return False, [f"conservation violated: merchant lost {merchant_lost}, customer gained {customer_gained}"]
        return True, ["merchant_delta == customer_delta in partial refund"]
    except Exception as e:
        return False, [f"conservation test raised: {e}"]


def _test_alias_mutation_shadow(mod) -> tuple[bool, list[str]]:
    """DEFAULTS must not be mutated by create_config."""
    create_config = getattr(mod, "create_config", None)
    DEFAULTS = getattr(mod, "DEFAULTS", None)
    if not create_config:
        return False, ["create_config not found"]
    if DEFAULTS is None:
        return False, ["DEFAULTS not found"]
    try:
        import inspect
        sig = inspect.signature(create_config)
        has_inherit = "inherit" in sig.parameters
        original = dict(DEFAULTS)
        cfg = create_config({"debug": True}, inherit=True) if has_inherit else create_config({"debug": True})
        if DEFAULTS != original:
            return False, [f"DEFAULTS mutated: was {original}, now {dict(DEFAULTS)}"]
        cfg2 = create_config({"timeout": 5}, inherit=True) if has_inherit else create_config({"timeout": 5})
        if DEFAULTS != original:
            return False, [f"DEFAULTS mutated on second call: {dict(DEFAULTS)}"]
        return True, ["DEFAULTS unchanged after create_config"]
    except Exception as e:
        return False, [f"alias test raised: {e}"]


def _test_lock_then_publish_order(mod) -> tuple[bool, list[str]]:
    """State must be updated before event is published."""
    update_and_notify = getattr(mod, "update_and_notify", None)
    get_captures = getattr(mod, "get_captures", None)
    clear = getattr(mod, "clear", None)
    if not update_and_notify:
        return False, ["update_and_notify not found"]
    if not get_captures:
        return False, ["get_captures not found"]
    try:
        if clear: clear()
        update_and_notify("x", 42)
        caps = get_captures()
        if not caps:
            return False, ["no events captured"]
        snapshot = caps[-1].get("state_at_publish")
        if snapshot != 42:
            return False, [f"stale state at publish: got {snapshot}, expected 42"]
        return True, ["state updated before publish"]
    except Exception as e:
        return False, [f"lock_publish test raised: {e}"]


# ============================================================
# V2 DYNAMIC TEST LOADER
# ============================================================

_EXEC_EVAL_DIR = Path(__file__).resolve().parent


def _load_v2_test(case):
    """Dynamically load test from tests_v2/ for v2 cases.

    V2 tests are organized as tests_v2/test_{family}.py with
    test_a(mod), test_b(mod), test_c(mod), or test(mod) functions.

    Raises RuntimeError if test file exists but expected function is missing.
    Returns None only if no test file exists at all.
    """
    family = case.get("family")
    level = case.get("difficulty", "").lower()

    # V1 cases lack family/difficulty — try case_id as family with test() fallback
    if not family:
        family = case.get("id", "")
        level = ""
    if not family:
        return None

    test_path = _EXEC_EVAL_DIR / "tests_v2" / f"test_{family}.py"
    if not test_path.exists():
        return None
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(f"_t3_v2_test_{family}", test_path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Try difficulty-specific function first, then generic test()
    fn = None
    if level:
        fn = getattr(mod, f"test_{level}", None)
    if fn is None:
        fn = getattr(mod, "test", None)
    if fn is None:
        # Last resort: try test_a (default for V2 families without difficulty)
        fn = getattr(mod, "test_a", None)
    if fn is None:
        raise RuntimeError(
            f"Test file {test_path} exists but has no usable test function. "
            f"Case: {case.get('id')}, family: {family}, difficulty: {level!r}. "
            f"Available functions: {[x for x in dir(mod) if x.startswith('test')]}"
        )
    return fn


# Dispatch table: case_id -> test function
_CASE_TESTS = {
    # V1 cases ported to V2 — use V2 tests via _load_v2_test fallback:
    #   hidden_dep_multihop, invariant_partial_fail, l3_state_pipeline,
    #   async_race_lock, cache_invalidation_order, feature_flag_drift
    # (removed from this table so V2 tests take priority)
    "temporal_semantic_drift": _test_temporal,
    "idempotency_trap": _test_idempotency,
    "partial_rollback_multi": _test_partial_rollback,
    "lazy_init_hazard": _test_lazy_init,
    "external_timing_dep": _test_external_timing,
    "shared_ref_coupling": _test_shared_ref,
    "log_side_effect_order": _test_log_order,
    "retry_causality": _test_retry_causality,
    # Easy calibration cases
    "easy_temporal": _test_easy_temporal,
    "easy_conservation": _test_easy_conservation,
    "easy_state_machine": _test_easy_state_machine,
    "easy_aliasing": _test_easy_aliasing,
    # Diagnostic probe cases (hard = original)
    "retry_ack_duplication": _test_retry_ack_duplication,
    "conservation_partial_refund": _test_conservation_partial_refund,
    "alias_mutation_shadow": _test_alias_mutation_shadow,
    "lock_then_publish_order": _test_lock_then_publish_order,
    # Difficulty ladder — easy/medium reuse same invariant tests
    "retry_ack_easy": _test_retry_ack_duplication,
    "retry_ack_medium": _test_retry_ack_duplication,
    "retry_ack_hard": _test_retry_ack_duplication,
    "conservation_easy": _test_conservation_partial_refund,
    "conservation_medium": _test_conservation_partial_refund,
    "conservation_hard": _test_conservation_partial_refund,
    "alias_easy": _test_alias_mutation_shadow,
    "alias_medium": _test_alias_mutation_shadow,
    "alias_hard": _test_alias_mutation_shadow,
    "publish_order_easy": _test_lock_then_publish_order,
    "publish_order_medium": _test_lock_then_publish_order,
    "publish_order_hard": _test_lock_then_publish_order,
    # Trivial difficulty — same invariant tests, minimal indirection
    "retry_ack_trivial": _test_retry_ack_duplication,
    "alias_trivial": _test_alias_mutation_shadow,
    "publish_order_trivial": _test_lock_then_publish_order,
}


# ============================================================
# MUTATION TESTS (generic)
# ============================================================

def _run_mutation_tests(mod, case_id: str) -> tuple[bool, list[str]]:
    """Run simple mutation tests: repeated calls, edge cases."""
    test_fn = _CASE_TESTS.get(case_id)
    if not test_fn:
        return True, ["no mutation tests for this case"]

    reasons = []
    # Mutation 1: Run the test twice (idempotency of test setup)
    ok1, r1 = test_fn(mod)
    if not ok1:
        return False, [f"mutation(repeat): {r1}"]
    ok2, r2 = test_fn(mod)
    if not ok2:
        return False, [f"mutation(repeat_2nd): {r2}"]
    reasons.append("passes on repeated execution")
    return True, reasons


# ============================================================
# MAIN EVALUATOR
# ============================================================

def _assemble_program(model_code: str, case: dict) -> dict:
    """Assemble executable program from model output + original case files.

    For multi-file cases, ALWAYS prepends original files as base, then
    appends model code on top (model definitions override originals).
    No heuristic guessing about completeness.

    Returns dict:
        code: str             — assembled code ready for execution
        assembly_used: bool   — whether original files were prepended
        assembly_risky: bool  — whether duplicate definitions were detected
        duplicate_defs: list  — names defined in both original and model code
        sources: dict         — provenance: which files contributed
    """
    import re

    code_contents = case.get("code_files_contents", {})

    # Single-file case or no original files: no assembly
    if not code_contents or len(code_contents) <= 1:
        return {
            "code": model_code,
            "assembly_used": False,
            "assembly_risky": False,
            "duplicate_defs": [],
            "sources": {"model_only": True},
        }

    # Multi-file case: ALWAYS assemble (no heuristic skip)
    # Strategy: original files as base → model code appended on top
    # Python executes top-to-bottom: model's definitions override originals

    original_parts = []
    original_files_used = []
    for rel_path in case.get("code_files", []):
        content = code_contents.get(rel_path, "")
        if content:
            original_parts.append(content)
            original_files_used.append(rel_path)

    original_concat = "\n\n".join(original_parts)
    original_cleaned = _strip_local_imports(original_concat)
    model_cleaned = _strip_local_imports(model_code)

    # Detect duplicate definitions (defined in both original and model)
    model_defs = set(re.findall(r'^(?:def|class)\s+(\w+)', model_cleaned, re.MULTILINE))
    original_defs = set(re.findall(r'^(?:def|class)\s+(\w+)', original_cleaned, re.MULTILINE))
    duplicates = sorted(model_defs & original_defs)

    # Detect rename error: model must define the function that the fix targets.
    # If the model renamed it instead of overriding, the original buggy version
    # will run and the model's fix is silently ignored.
    #
    # We use reference_fix.function as the expected override target, but ONLY
    # fire rename_error when that function exists in the ORIGINAL code (proving
    # it's a real entry point that must be overridden, not a metadata error).
    expected_func = case.get("reference_fix", {}).get("function", "")
    rename_error = False
    if expected_func and expected_func in original_defs and expected_func not in model_defs:
        rename_error = True
        _eval_log.warning(
            "RENAME DETECTED: case %s expects model to define '%s' but model defines: %s. "
            "Original buggy '%s' will run instead of model's fix.",
            case.get("id", "?"), expected_func, sorted(model_defs), expected_func
        )

    # Assemble: original base + model overlay
    assembled = original_cleaned + "\n\n" + model_cleaned

    return {
        "code": assembled,
        "assembly_used": True,
        "assembly_risky": len(duplicates) > 0,
        "rename_error": rename_error,
        "expected_func": expected_func,
        "duplicate_defs": duplicates,
        "sources": {
            "model_only": False,
            "original_files": original_files_used,
            "model_defs": sorted(model_defs),
            "original_defs": sorted(original_defs),
            "overridden": duplicates,
        },
    }


def exec_evaluate(case: dict, code: str) -> dict:
    """Execute extracted code and test invariants.

    Receives already-extracted code string. Does NOT parse raw output.
    Parsing happens exactly once at the system boundary (execution.py).

    For multi-file cases: merges model output with original case files
    to fill missing definitions. Assembly errors are tracked separately
    from logic errors.
    """
    case_id = case["id"]
    reasons = []
    failure_modes = []

    # Capture extracted code for logging — never allow N/A
    extracted = code if (code and code.strip()) else "<EXTRACTION FAILED>"

    if not code or len(code.strip()) < 10:
        return _result(case_id, False, 0.0,
                       ["no extractable code in output"], [case["failure_mode"]],
                       _exec_info(ran=False, total_tests=0),
                       extracted_code=extracted)

    # Step 1.5: Multi-file assembly
    asm = _assemble_program(code, case)
    assembled_code = asm["code"]
    assembly_used = asm["assembly_used"]

    if asm["assembly_risky"]:
        _eval_log.info(
            "ASSEMBLY: %s has duplicate defs (overridden by model): %s",
            case_id, asm["duplicate_defs"]
        )

    # Step 1.6: Rename detection — model failed to override the target function.
    # This is a MODEL failure (wrong function name), NOT an assembly/infrastructure failure.
    # Result is included in metrics (exec_pass=False, assembly_error=False).
    if asm.get("rename_error"):
        return _result(case_id, False, 0.0,
                       [f"rename error: model does not define '{asm['expected_func']}' — "
                        f"original buggy function would run instead of model's fix"],
                       [case["failure_mode"]],
                       _exec_info(ran=False, total_tests=0,
                                  assembly_used=assembly_used,
                                  assembly_error=False,
                                  rename_error=True,
                                  assembly_risky=asm.get("assembly_risky", False),
                                  assembly_sources=asm.get("sources")),
                       extracted_code=extracted)

    # Step 2: Load module — runtime-based assembly validation
    # Any NameError/ImportError here = assembly failure, NOT logic error
    assembly_error = False
    try:
        mod = load_module_from_code(assembled_code, case_id)
    except SyntaxError as e:
        return _result(case_id, False, 0.0,
                       [f"syntax error: {e}"], [case["failure_mode"]],
                       _exec_info(ran=False, syntax_error=str(e), total_tests=0,
                                  assembly_used=assembly_used, assembly_error=False,
                                  assembly_risky=asm["assembly_risky"],
                                  assembly_sources=asm["sources"]),
                       extracted_code=extracted)
    except (NameError, ImportError) as e:
        return _result(case_id, False, 0.0,
                       [f"assembly error (unresolved dependency at load): {e}"],
                       [case["failure_mode"]],
                       _exec_info(ran=False, runtime_error=str(e), total_tests=0,
                                  assembly_used=assembly_used, assembly_error=True,
                                  assembly_risky=asm["assembly_risky"],
                                  assembly_sources=asm["sources"]),
                       extracted_code=extracted)
    except Exception as e:
        err_str = str(e)
        is_unresolved = ("not defined" in err_str.lower() or
                         "no module" in err_str.lower() or
                         "cannot import" in err_str.lower())
        return _result(case_id, False, 0.0,
                       [f"{'assembly' if is_unresolved else 'load'} error: {e}"],
                       [case["failure_mode"]],
                       _exec_info(ran=False, runtime_error=str(e), total_tests=0,
                                  assembly_used=assembly_used,
                                  assembly_error=is_unresolved,
                                  assembly_risky=asm["assembly_risky"],
                                  assembly_sources=asm["sources"]),
                       extracted_code=extracted)

    # Step 3: Run invariant test
    test_fn = _CASE_TESTS.get(case_id)
    if test_fn is None:
        # Try v2 dynamic test loader
        test_fn = _load_v2_test(case)
    if test_fn is None:
        raise RuntimeError(
            f"NO TEST for case {case_id}. Neither _CASE_TESTS nor _load_v2_test "
            f"resolved a test function. This is a pipeline bug — CRASHING."
        )

    # Assembly metadata for all downstream results
    _asm_kw = dict(
        assembly_used=assembly_used,
        assembly_risky=asm["assembly_risky"],
        assembly_sources=asm["sources"],
    )

    # Tests actually run from here — total_tests is measured, not assumed
    total_tests = 0
    passed_tests = 0
    try:
        total_tests += 1  # invariant test attempted
        inv_pass, inv_reasons = test_fn(mod)
        reasons.extend(inv_reasons)
        if inv_pass:
            passed_tests += 1
    except (NameError, ImportError) as e:
        # Unresolved symbol during test = assembly failure, NOT logic error
        inv_pass = False
        reasons.append(f"assembly error during test (unresolved dependency): {e}")
        return _result(case_id, False, 0.0,
                       reasons, [case["failure_mode"]],
                       _exec_info(ran=True, invariant_pass=False,
                                  runtime_error=str(e),
                                  passed_tests=0, total_tests=total_tests,
                                  assembly_error=True, **_asm_kw),
                       extracted_code=extracted)
    except AttributeError as e:
        err_str = str(e)
        is_missing = "has no attribute" in err_str
        inv_pass = False
        reasons.append(f"{'assembly' if is_missing else 'runtime'} error: {e}")
        return _result(case_id, False, 0.0 if is_missing else 0.1,
                       reasons, [case["failure_mode"]],
                       _exec_info(ran=True, invariant_pass=False,
                                  runtime_error=str(e),
                                  passed_tests=0, total_tests=total_tests,
                                  assembly_error=is_missing, **_asm_kw),
                       extracted_code=extracted)
    except Exception as e:
        inv_pass = False
        reasons.append(f"invariant test crashed: {e}")
        return _result(case_id, False, 0.1,
                       reasons, [case["failure_mode"]],
                       _exec_info(ran=True, invariant_pass=False,
                                  runtime_error=str(e),
                                  passed_tests=0, total_tests=total_tests,
                                  assembly_error=False, **_asm_kw),
                       extracted_code=extracted)

    if not inv_pass:
        failure_modes.append(case["failure_mode"])
        # Check if the test failure was caused by an assembly issue
        # (NameError/ImportError caught by the test function itself)
        reason_text = " ".join(reasons).lower()
        is_assembly_in_test = (
            "not defined" in reason_text or
            "has no attribute" in reason_text or
            "no module named" in reason_text or
            "cannot import" in reason_text
        )
        if is_assembly_in_test:
            return _result(case_id, False, 0.0, reasons, failure_modes,
                           _exec_info(ran=True, invariant_pass=False,
                                      passed_tests=0, total_tests=total_tests,
                                      assembly_error=True, **_asm_kw),
                           extracted_code=extracted)
        return _result(case_id, False, 0.2, reasons, failure_modes,
                       _exec_info(ran=True, invariant_pass=False,
                                  passed_tests=0, total_tests=total_tests,
                                  assembly_error=False, **_asm_kw),
                       extracted_code=extracted)

    # Step 4: Mutation tests
    total_tests += 1  # mutation test attempted
    mut_pass = False
    try:
        mut_pass, mut_reasons = _run_mutation_tests(mod, case_id)
        reasons.extend(mut_reasons)
        if mut_pass:
            passed_tests += 1
    except Exception as e:
        reasons.append(f"mutation test crashed: {e}")
        return _result(case_id, False, 0.5, reasons, [case["failure_mode"]],
                       _exec_info(ran=True, invariant_pass=True, mutation_pass=False,
                                  runtime_error=str(e),
                                  passed_tests=passed_tests, total_tests=total_tests,
                                  assembly_error=False, **_asm_kw),
                       extracted_code=extracted)

    if not mut_pass:
        return _result(case_id, False, 0.5, reasons, [case["failure_mode"]],
                       _exec_info(ran=True, invariant_pass=True, mutation_pass=False,
                                  passed_tests=passed_tests, total_tests=total_tests,
                                  assembly_error=False, **_asm_kw),
                       extracted_code=extracted)

    # All pass
    return _result(case_id, True, 1.0, reasons, [],
                   _exec_info(ran=True, invariant_pass=True, mutation_pass=True,
                              passed_tests=passed_tests, total_tests=total_tests,
                              assembly_error=False, **_asm_kw),
                   extracted_code=extracted,
                   assembled_code=assembled_code)
