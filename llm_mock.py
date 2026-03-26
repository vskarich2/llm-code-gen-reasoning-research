"""Deterministic mock LLM responses for T3 benchmark.

Each case returns JSON-formatted {reasoning, code}.
Baseline = plausible-but-wrong fix. Nudged = correct fix.
"""

import json


def _json_resp(reasoning: str, code: str) -> str:
    return json.dumps({"reasoning": reasoning, "code": code})


def mock_call(prompt: str) -> str:
    """Dispatch to case-specific mock based on prompt keywords."""
    out = prompt.lower()

    # LLM reasoning classifier prompt detection (must be first)
    if "reasoning_correct" in out and "failure_type" in out and "reasoning quality" in out:
        return _mock_classify(out)

    # LEG-reduction prompt detection (must be before generic dispatch)
    if "bug_diagnosis" in out and "plan_steps" in out and "verification" in out:
        return _mock_leg_reduction(out)

    guardrail = "mandatory constraints" in out
    diagnostic = "stop. before" in out
    nudged = guardrail or diagnostic

    for keywords, handler in _DISPATCH:
        if any(k in out for k in keywords):
            return handler(nudged, guardrail)

    return _json_resp("No changes needed.", "# no changes")


def _mock_classify(out):
    """Mock for the reasoning-only LLM classifier.

    Determines reasoning_correct from presence of mechanism keywords.
    Does NOT judge code correctness — that comes from execution.
    Returns 2-part format: REASONING_CORRECT ; FAILURE_TYPE
    """
    # Check reasoning by looking for mechanism keywords
    mechanism_keywords = [
        "rollback", "frozen", "overwrite", "cache_put", "raw_stats",
        "commit", "failure window", "debit", "invariant", "atomic",
        "conservation", "stale", "order", "dependency",
    ]
    reasoning_correct = any(kw in out for kw in mechanism_keywords)

    # Infer failure type
    if "frozen" in out or "commit" in out or "stage" in out:
        ftype = "PARTIAL_STATE_UPDATE"
    elif "cache" in out or "overwrite" in out:
        ftype = "HIDDEN_DEPENDENCY"
    elif "raw_stats" in out or "transform" in out or "before" in out:
        ftype = "TEMPORAL_ORDERING"
    elif "rollback" in out or "debit" in out or "balance" in out:
        ftype = "INVARIANT_VIOLATION"
    else:
        ftype = "UNKNOWN"

    rc = "YES" if reasoning_correct else "NO"
    return f"{rc} ; {ftype}"


# ── Per-case mock handlers ───────────────────────────────────

def _mock_hidden_dep(nudged, guardrail):
    if nudged:
        return _json_resp(
            "sync_user_to_cache uses cache_put (always overwrites). Must keep write-through.",
            "from user_repo import persist_user, remove_user\n"
            "from cache_writer import cache_delete, sync_user_to_cache\n\n"
            "def save_user(user):\n"
            "    persist_user(user)\n"
            "    sync_user_to_cache(user)\n",
        )
    return _json_resp(
        "Simplified coupling by using refresh_user_snapshot.",
        "from user_repo import persist_user, remove_user\n"
        "from cache_writer import cache_delete, refresh_user_snapshot\n\n"
        "def save_user(user):\n"
        "    persist_user(user)\n"
        "    refresh_user_snapshot(user)\n",
    )


def _mock_state_pipeline(nudged, guardrail):
    if guardrail:
        return _json_resp(
            "All three steps required. commit sets frozen, preview uses stage without commit.",
            "def process_batch(entries):\n"
            "    st = make_state(entries)\n"
            "    cleaned = normalize(st['raw'])\n"
            "    merged = collapse(cleaned)\n"
            "    stage(st, merged)\n"
            "    commit(st)\n"
            "    freeze_view(st)\n"
            "    return st, materialize(st)\n",
        )
    return _json_resp(
        "stage() already writes pending and view. commit and freeze_view are redundant.",
        "def process_batch(entries):\n"
        "    st = make_state(entries)\n"
        "    cleaned = normalize(st['raw'])\n"
        "    merged = collapse(cleaned)\n"
        "    stage(st, merged)\n"
        "    return st, materialize(st)\n",
    )


def _mock_temporal(nudged, guardrail):
    if nudged:
        return _json_resp(
            "compute_raw_stats must run on original data before transforms.",
            "def pipeline(data):\n"
            "    raw_stats = compute_raw_stats(data)\n"
            "    cleaned = clip_negatives(normalize(smooth(data)))\n"
            "    quality = compute_quality_score(cleaned)\n"
            "    return {'raw_stats': raw_stats, 'quality': quality, 'cleaned': cleaned}\n",
        )
    return _json_resp(
        "Reduced passes by computing everything after transforms.",
        "def pipeline(data):\n"
        "    cleaned = clip_negatives(normalize(smooth(data)))\n"
        "    raw_stats = compute_raw_stats(cleaned)\n"
        "    quality = compute_quality_score(cleaned)\n"
        "    return {'raw_stats': raw_stats, 'quality': quality, 'cleaned': cleaned}\n",
    )


def _mock_invariant(nudged, guardrail):
    if nudged:
        return _json_resp(
            "Failure window after debit before credit. Need rollback.",
            "def execute_transfer(sender, receiver, amount):\n"
            "    validate_transfer(sender, amount)\n"
            "    sender.balance -= amount\n"
            "    try:\n"
            "        receiver.balance += amount\n"
            "    except Exception:\n"
            "        sender.balance += amount\n"
            "        raise\n",
        )
    return _json_resp(
        "Added error handling and reasoning_evaluator_audit logging.",
        "def execute_transfer(sender, receiver, amount):\n"
        "    validate_transfer(sender, amount)\n"
        "    sender.balance -= amount\n"
        "    try:\n"
        "        receiver.balance += amount\n"
        "    except RuntimeError as e:\n"
        "        emit_failure_alert(sender.account_id, receiver.account_id, amount, e)\n"
        "        raise\n",
    )


def _mock_leg_reduction(out):
    """Mock for LEG-reduction condition. Returns full revision trace schema."""
    code_fixed = (
        "def process_batch(entries):\n"
        "    st = make_state(entries)\n"
        "    cleaned = normalize(st['raw'])\n"
        "    merged = collapse(cleaned)\n"
        "    stage(st, merged)\n"
        "    commit(st)\n"
        "    freeze_view(st)\n"
        "    return st, materialize(st)\n"
    )
    verification_pass = [
        {"step": "Preserve commit() call", "status": "PASS", "evidence": "commit(st) present at line 7"},
        {"step": "Preserve freeze_view() call", "status": "PASS", "evidence": "freeze_view(st) present at line 8"},
    ]

    if "process_batch" in out or "reducers" in out or "selectors" in out:
        return json.dumps({
            "bug_diagnosis": "commit() sets frozen=True which get_committed_total checks. Removing it breaks the invariant.",
            "plan_steps": [
                {"step": "Preserve commit() call", "intended_effect": "frozen flag is set to True"},
                {"step": "Preserve freeze_view() call", "intended_effect": "view reflects stable state"},
            ],
            "revision_history": [{
                "revision": 0,
                "verification": verification_pass,
                "invariants_checked": [
                    {"invariant": "frozen==True after process_batch", "status": "PASS",
                     "evidence": "commit(st) sets meta['frozen']=True"},
                ],
                "issues_found": [],
                "changes_made": None,
                "changed_functions": [],
                "code_before": "def process_batch(entries): ...",
                "code_after": code_fixed,
            }],
            "verification": verification_pass,
            "code": code_fixed,
            "internal_revisions": 0,
        })

    if "execute_transfer" in out or "transfer_service" in out:
        code_fixed_inv = (
            "def execute_transfer(sender, receiver, amount):\n"
            "    validate_transfer(sender, amount)\n"
            "    sender.balance -= amount\n"
            "    try:\n"
            "        receiver.balance += amount\n"
            "    except Exception:\n"
            "        sender.balance += amount\n"
            "        raise\n"
        )
        v_pass = [
            {"step": "Add try/except around credit", "status": "PASS", "evidence": "try: block wraps receiver.balance += amount"},
            {"step": "Restore balance in except", "status": "PASS", "evidence": "except block has sender.balance += amount"},
        ]
        return json.dumps({
            "bug_diagnosis": "Failure window between debit and credit. Exception after debit loses money.",
            "plan_steps": [
                {"step": "Add try/except around credit", "intended_effect": "catch failures after debit"},
                {"step": "Restore balance in except", "intended_effect": "rollback on failure"},
            ],
            "revision_history": [{
                "revision": 0,
                "verification": v_pass,
                "invariants_checked": [
                    {"invariant": "sender.balance + receiver.balance == constant", "status": "PASS",
                     "evidence": "except block restores sender.balance"},
                ],
                "issues_found": [],
                "changes_made": None,
                "changed_functions": [],
                "code_before": "def execute_transfer(sender, receiver, amount): ...",
                "code_after": code_fixed_inv,
            }],
            "verification": v_pass,
            "code": code_fixed_inv,
            "internal_revisions": 0,
        })

    # Generic fallback
    generic_v = [{"step": "Fix identified issue", "status": "PASS", "evidence": "change applied"}]
    return json.dumps({
        "bug_diagnosis": "Identified root cause in code logic.",
        "plan_steps": [{"step": "Fix identified issue", "intended_effect": "Correct behavior restored"}],
        "revision_history": [{
            "revision": 0,
            "verification": generic_v,
            "invariants_checked": [
                {"invariant": "output matches expected", "status": "PASS", "evidence": "code produces correct result"},
            ],
            "issues_found": [],
            "changes_made": None,
            "changed_functions": [],
            "code_before": "# original",
            "code_after": "# no specific fix available\npass\n",
        }],
        "verification": generic_v,
        "code": "# no specific fix available\npass\n",
        "internal_revisions": 0,
    })


# ── Dispatch table ───────────────────────────────────────────

_DISPATCH = [
    # Order matters: check specific keywords before generic ones
    (["cache_writer", "user_service"], _mock_hidden_dep),
    (["process_batch", "reducers", "selectors"], _mock_state_pipeline),
    (["compute_raw_stats", "pipeline"], _mock_temporal),
    (["execute_transfer", "transfer_service"], _mock_invariant),
]
