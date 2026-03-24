"""SCM (Structural Causal Model) evidence data for T3 cases.

Each case has: functions (F*), variables (V*), edges (E*),
invariants (I*), constraints (C*), and a critical_evidence_set.
"""

SCM_REGISTRY: dict[str, dict] = {}


def _r(case_id, scm):
    SCM_REGISTRY[case_id] = scm


def get_scm(case_id: str) -> dict | None:
    return SCM_REGISTRY.get(case_id)


# ════════════════════════════════════════════════════════════
# hidden_dep_multihop
# ════════════════════════════════════════════════════════════

_r("hidden_dep_multihop", {
    "functions": {
        "F1": "save_user(user) in user_service.py",
        "F2": "persist_user(user) calls db.insert(user)",
        "F3": "sync_user_to_cache(user) calls cache_put(f'user:{user[\"id\"]}', user['name'])",
        "F4": "get_display_name(user_id) returns _store.get(f'user:{user_id}')",
        "F5": "refresh_user_snapshot(user) calls cache_put_if_absent() — does NOT overwrite",
        "F6": "cache_put(key, value) always sets _store[key] = value",
        "F7": "cache_put_if_absent(key, value) only writes if key NOT in _store",
    },
    "variables": {
        "V1": "_store dict in cache_writer.py (shared in-memory cache)",
    },
    "edges": {
        "E1": "F1 → F3: save_user() calls sync_user_to_cache()",
        "E2": "F3 → V1: sync_user_to_cache() writes to _store via F6 (cache_put)",
        "E3": "V1 → F4: get_display_name() reads from _store",
        "E4": "F5 → V1: refresh_user_snapshot() writes to _store via F7 (cache_put_if_absent)",
    },
    "invariants": {
        "I1": "After save_user({'id':'u1','name':'Alice'}): _store.get('user:u1') == 'Alice'",
        "I2": "After save_user({'id':'u1','name':'Bob'}): _store.get('user:u1') == 'Bob' (overwrite)",
    },
    "constraints": {
        "C1": {"text": "F1 must call F3 — removing E1 breaks E2→E3 chain, making F4 return None",
               "edges": ["E1", "E2", "E3"], "functions": ["F1", "F3", "F4"], "invariants": ["I1"]},
        "C2": {"text": "F3 must use F6 (cache_put), not F7 (cache_put_if_absent) — F7 won't overwrite",
               "edges": ["E2"], "functions": ["F3", "F6", "F7"], "invariants": ["I2"]},
    },
    "critical_evidence_set": {
        "functions": ["F3", "F4", "F6", "F7"],
        "edges": ["E2", "E3"],
        "invariants": ["I2"],
        "constraints": ["C2"],
    },
    "critical_constraint": {
        "id": "C2",
        "why_fragile": "F6 and F7 have identical signatures and similar names. Both write to V1. The difference is ONLY overwrite behavior.",
        "failure_trace": "save_user({'id':'u1','name':'Alice'}) → _store['user:u1']='Alice'. "
                         "save_user({'id':'u1','name':'Bob'}) with F7 → _store['user:u1'] stays 'Alice'. "
                         "get_display_name('u1') returns 'Alice' instead of 'Bob'.",
    },
})


# ════════════════════════════════════════════════════════════
# l3_state_pipeline
# ════════════════════════════════════════════════════════════

_r("l3_state_pipeline", {
    "functions": {
        "F1": "make_state(entries) creates state dict with raw, pending, stable, view, meta",
        "F2": "stage(st, merged) writes to st['pending'] and st['view'], bumps version",
        "F3": "commit(st) copies st['pending'] → st['stable'], sets st['meta']['frozen']=True",
        "F4": "freeze_view(st) rebuilds st['view'] from st['stable'] via project()",
        "F5": "get_committed_total(st) checks st['meta']['frozen'], sums st['stable']",
        "F6": "preview() in api.py calls F2 (stage) WITHOUT calling F3 (commit)",
        "F7": "materialize(st) returns dict from st['stable'] and st['view']",
    },
    "variables": {
        "V1": "st['pending'] — staged data",
        "V2": "st['stable'] — committed data",
        "V3": "st['meta']['frozen'] — flag checked by F5",
        "V4": "st['view'] — display projection",
    },
    "edges": {
        "E1": "F2 → V1: stage() writes to st['pending']",
        "E2": "F3 → V2: commit() copies V1 → V2",
        "E3": "F3 → V3: commit() sets st['meta']['frozen']=True",
        "E4": "V3 → F5: get_committed_total() checks V3 before reading V2",
        "E5": "F4 → V4: freeze_view() rebuilds st['view'] from V2",
        "E6": "F2 → F6: preview() uses F2 independently of F3",
    },
    "invariants": {
        "I1": "After process_batch(): st['meta']['frozen'] == True",
        "I2": "After process_batch(): get_committed_total(st) is not None",
        "I3": "After preview(): st['meta']['frozen'] == False",
    },
    "constraints": {
        "C1": {"text": "F3 must not be removed — E3 sets V3 which F5 checks via E4",
               "edges": ["E3", "E4"], "functions": ["F3", "F5"], "invariants": ["I1", "I2"]},
        "C2": {"text": "F2 and F3 must remain separate — F6 calls F2 without F3 via E6",
               "edges": ["E6"], "functions": ["F2", "F3", "F6"], "invariants": ["I3"]},
    },
    "critical_evidence_set": {
        "functions": ["F2", "F3", "F5", "F6"],
        "edges": ["E3", "E4", "E6"],
        "invariants": ["I1", "I3"],
        "constraints": ["C1", "C2"],
    },
    "critical_constraint": {
        "id": "C1",
        "why_fragile": "stage() and commit() both write to state, making commit() look redundant. "
                       "But only commit() sets the frozen flag that get_committed_total() checks.",
        "failure_trace": "Remove commit() → st['meta']['frozen'] stays False → "
                         "get_committed_total(st) returns None → api.ingest() returns {'total': None}.",
    },
})


# ════════════════════════════════════════════════════════════
# temporal_semantic_drift
# ════════════════════════════════════════════════════════════

_r("temporal_semantic_drift", {
    "functions": {
        "F1": "pipeline(data) — main entry point",
        "F2": "compute_raw_stats(data) returns raw_mean, raw_max, raw_min, raw_range",
        "F3": "smooth(data) applies moving average",
        "F4": "normalize(smoothed) scales to [0,1]",
        "F5": "clip_negatives(normalized) zeros negatives",
        "F6": "compute_quality_score(cleaned) counts zeros",
        "F7": "build_report() reads result['raw_stats']['raw_max'] etc.",
        "F8": "summarize_for_display() — different keys, NOT a substitute for F2",
    },
    "variables": {
        "V1": "data — original raw sensor values",
        "V2": "cleaned — post-transform data",
    },
    "edges": {
        "E1": "V1 → F2: compute_raw_stats must receive original data",
        "E2": "V2 → F6: compute_quality_score must receive cleaned data",
        "E3": "F2 → F7: build_report reads raw_stats keys",
    },
    "invariants": {
        "I1": "raw_stats['raw_max'] == max(original_data), not 1.0",
        "I2": "raw_stats keys are raw_mean, raw_max, raw_min, raw_range",
    },
    "constraints": {
        "C1": {"text": "F2 must receive V1 (original data), not V2 (cleaned)",
               "edges": ["E1"], "functions": ["F2"], "invariants": ["I1"]},
        "C2": {"text": "F8 is NOT a substitute for F2 — different keys",
               "edges": ["E3"], "functions": ["F2", "F7", "F8"], "invariants": ["I2"]},
    },
    "critical_evidence_set": {
        "functions": ["F2", "F7"],
        "edges": ["E1", "E3"],
        "invariants": ["I1"],
        "constraints": ["C1"],
    },
    "critical_constraint": {
        "id": "C1",
        "why_fragile": "After normalize(), max(data)=1.0. If F2 runs on normalized data, raw_max=1.0 "
                       "instead of the actual sensor peak. build_report() silently reports wrong values.",
        "failure_trace": "pipeline([10,20,30,40,50]) with F2 on cleaned → raw_max≈1.0 instead of 50.",
    },
})


# ════════════════════════════════════════════════════════════
# invariant_partial_fail
# ════════════════════════════════════════════════════════════

_r("invariant_partial_fail", {
    "functions": {
        "F1": "validate_transfer(sender, amount) checks preconditions",
        "F2": "execute_transfer(sender, receiver, amount) — main function",
        "F3": "sender.balance -= amount (debit)",
        "F4": "receiver.balance += amount (credit)",
        "F5": "record_transfer_attempt() — observability only",
        "F6": "emit_failure_alert() — observability only",
    },
    "variables": {
        "V1": "sender.balance",
        "V2": "receiver.balance",
        "V3": "V1 + V2 (total, must be conserved)",
    },
    "edges": {
        "E1": "F1 → F3: validate before debit",
        "E2": "F3 → V1: debit decreases sender balance",
        "E3": "F4 → V2: credit increases receiver balance",
        "E4": "E2 → E3: temporal gap — RuntimeError can occur between debit and credit",
    },
    "invariants": {
        "I1": "V1 + V2 == total_before after any execution path (conservation)",
    },
    "constraints": {
        "C1": {"text": "If F3 executes and F4 fails, F3 must be rolled back (V1 restored)",
               "edges": ["E2", "E3", "E4"], "functions": ["F3", "F4"], "invariants": ["I1"]},
        "C2": {"text": "F5 and F6 are observability — they do NOT protect I1",
               "edges": [], "functions": ["F5", "F6"], "invariants": ["I1"]},
    },
    "critical_evidence_set": {
        "functions": ["F3", "F4"],
        "edges": ["E2", "E4"],
        "invariants": ["I1"],
        "constraints": ["C1"],
    },
    "critical_constraint": {
        "id": "C1",
        "why_fragile": "F3 and F4 look like a simple pair. But a RuntimeError between them "
                       "means F3 ran (money debited) and F4 did not (money not credited). "
                       "Adding logging (F5, F6) does not fix the conservation violation.",
        "failure_trace": "sender=100, receiver=0, transfer 50. F3 runs (sender=50). "
                         "RuntimeError. F4 never runs. Total=50, not 100. Money lost.",
    },
})


# ════════════════════════════════════════════════════════════
# noncommutative_ops (new planned case — SCM only for now)
# ════════════════════════════════════════════════════════════

_r("noncommutative_ops", {
    "functions": {
        "F1": "pipeline(amount, fee_rate, tax_rate) — entry point",
        "F2": "apply_fee(amount, fee_rate) returns amount - fee_rate",
        "F3": "apply_tax(amount, tax_rate) returns amount * (1 + tax_rate)",
    },
    "variables": {
        "V1": "amount — input value",
    },
    "edges": {
        "E1": "V1 → F2: fee applied to original amount",
        "E2": "F2 → F3: tax applied to fee-reduced amount",
    },
    "invariants": {
        "I1": "pipeline(100, 5, 0.1) == (100-5)*1.1 == 104.5",
    },
    "constraints": {
        "C1": {"text": "F2 must execute before F3 — (a-fee)*tax != a*tax-fee",
               "edges": ["E1", "E2"], "functions": ["F2", "F3"], "invariants": ["I1"]},
    },
    "critical_evidence_set": {
        "functions": ["F2", "F3"],
        "edges": ["E1", "E2"],
        "invariants": ["I1"],
        "constraints": ["C1"],
    },
    "critical_constraint": {
        "id": "C1",
        "why_fragile": "F2 (subtraction) and F3 (multiplication) look similar — both transform amount by rate. "
                       "But subtraction then multiplication != multiplication then subtraction.",
        "failure_trace": "fee(tax(100,0.1),5) = 100*1.1-5 = 105.0. tax(fee(100,5),0.1) = 95*1.1 = 104.5. "
                         "Swapping order changes result by 0.5.",
    },
})
