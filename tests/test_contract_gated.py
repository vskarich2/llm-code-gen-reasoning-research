"""Tests for Contract-Gated Execution (CGE).

Covers: contract parsing, diff gate checks, integration.
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"


# ════════════════════════════════════════════════════════════
# CONTRACT PARSING
# ════════════════════════════════════════════════════════════

def test_parse_valid_contract():
    from contract import parse_contract, ALLOWED_EFFECTS
    raw = json.dumps({
        "root_cause": "missing rollback",
        "must_change": ["transfer_service.py::execute_transfer"],
        "must_not_change": ["models.py::Account"],
        "required_effects": ["add_rollback_on_failure"],
        "side_effects": [{"effect": "credit", "when": "after", "relative_to": "debit"}],
        "retry_semantics": {"idempotency_key_required": False, "duplicate_effects_forbidden": []},
        "rollback_semantics": {"must_rollback_if": ["credit_fails_after_debit"], "must_not_persist_after_failure": []},
        "invariants": ["balance conservation"],
    })
    c = parse_contract(raw)
    assert c is not None
    assert c["root_cause"] == "missing rollback"
    assert c["_verifiable"] is True
    assert len(c["_unknown_effects"]) == 0


def test_parse_contract_markdown():
    from contract import parse_contract
    raw = 'Here is the contract:\n```json\n{"root_cause":"x","must_change":[],"must_not_change":[],"required_effects":[]}\n```'
    c = parse_contract(raw)
    assert c is not None
    assert c["root_cause"] == "x"


def test_parse_contract_missing_optional():
    from contract import parse_contract
    raw = json.dumps({"root_cause": "bug", "must_change": ["f::g"], "must_not_change": [], "required_effects": []})
    c = parse_contract(raw)
    assert c is not None
    assert c["side_effects"] == []
    assert c["invariants"] == []


def test_parse_contract_garbage():
    from contract import parse_contract
    c = parse_contract("this is not json at all")
    assert c is None


def test_parse_unknown_effects_flagged():
    from contract import parse_contract
    raw = json.dumps({
        "root_cause": "x", "must_change": [], "must_not_change": [],
        "required_effects": ["add_rollback_on_failure", "totally_made_up_effect"],
    })
    c = parse_contract(raw)
    assert c is not None
    assert "add_rollback_on_failure" in c["required_effects"]
    assert "totally_made_up_effect" not in c["required_effects"]
    assert "totally_made_up_effect" in c["_unknown_effects"]
    assert c["_verifiable"] is False


def test_parse_malformed_ordering():
    from contract import parse_contract
    raw = json.dumps({
        "root_cause": "x", "must_change": [], "must_not_change": [],
        "required_effects": [],
        "side_effects": [{"effect": "write", "when": "invalid_direction", "relative_to": "read"}],
    })
    c = parse_contract(raw)
    assert c is not None
    assert len(c["_unresolvable_orderings"]) > 0
    assert c["_verifiable"] is False


# ════════════════════════════════════════════════════════════
# DIFF GATE — STRUCTURAL
# ════════════════════════════════════════════════════════════

def test_must_change_present():
    from diff_gate import validate
    contract = {"must_change": ["service.py::save_user"], "must_not_change": [],
                "required_effects": [], "side_effects": [],
                "retry_semantics": {}, "rollback_semantics": {}}
    code = "def save_user(user):\n    db.save(user)\n"
    r = validate(contract, code, "")
    assert not any("must_change" in v for v in r["violations"])


def test_must_change_missing():
    from diff_gate import validate
    contract = {"must_change": ["service.py::save_user"], "must_not_change": [],
                "required_effects": [], "side_effects": [],
                "retry_semantics": {}, "rollback_semantics": {}}
    code = "def other_func():\n    pass\n"
    r = validate(contract, code, "")
    assert any("save_user" in v and "not found" in v for v in r["violations"])


def test_must_not_change_preserved():
    from diff_gate import validate
    ref = "def helper():\n    return 42\n"
    code = "def helper():\n    return 42\ndef save_user():\n    pass\n"
    contract = {"must_change": [], "must_not_change": ["util.py::helper"],
                "required_effects": [], "side_effects": [],
                "retry_semantics": {}, "rollback_semantics": {}}
    r = validate(contract, code, ref)
    assert not any("must_not_change" in v for v in r["violations"])


def test_must_not_change_modified():
    from diff_gate import validate
    ref = "def helper():\n    return 42\n"
    code = "def helper():\n    return 99\n"
    contract = {"must_change": [], "must_not_change": ["util.py::helper"],
                "required_effects": [], "side_effects": [],
                "retry_semantics": {}, "rollback_semantics": {}}
    r = validate(contract, code, ref)
    assert any("helper" in v and "modified" in v for v in r["violations"])


# ════════════════════════════════════════════════════════════
# DIFF GATE — REQUIRED EFFECTS
# ════════════════════════════════════════════════════════════

def test_idempotency_guard_present():
    from diff_gate import validate
    code = "def process(key, val):\n    if key in seen:\n        return\n    insert(key, val)\n"
    contract = {"must_change": [], "must_not_change": [], "side_effects": [],
                "required_effects": ["introduce_idempotency_guard"],
                "retry_semantics": {"duplicate_effects_forbidden": ["insert"]},
                "rollback_semantics": {}}
    r = validate(contract, code, "")
    assert not any("idempotency" in v.lower() for v in r["violations"])


def test_idempotency_guard_missing():
    from diff_gate import validate
    code = "def process(key, val):\n    insert(key, val)\n"
    contract = {"must_change": [], "must_not_change": [], "side_effects": [],
                "required_effects": ["introduce_idempotency_guard"],
                "retry_semantics": {"duplicate_effects_forbidden": ["insert"]},
                "rollback_semantics": {}}
    r = validate(contract, code, "")
    assert any("idempotency" in v.lower() or "guard" in v.lower() for v in r["violations"])


def test_rollback_with_compensation():
    from diff_gate import validate
    code = (
        "def transfer(a, b, amount):\n"
        "    a.balance -= amount\n"
        "    try:\n"
        "        b.balance += amount\n"
        "    except Exception:\n"
        "        a.balance += amount\n"
        "        raise\n"
    )
    contract = {"must_change": [], "must_not_change": [], "side_effects": [],
                "required_effects": ["add_rollback_on_failure"],
                "retry_semantics": {},
                "rollback_semantics": {"must_rollback_if": ["credit_fails_after_debit"],
                                       "must_not_persist_after_failure": []}}
    r = validate(contract, code, "")
    assert not any("ROLLBACK" in v for v in r["violations"])


def test_rollback_logging_only():
    from diff_gate import validate
    code = (
        "def transfer(a, b, amount):\n"
        "    a.balance -= amount\n"
        "    try:\n"
        "        b.balance += amount\n"
        "    except Exception:\n"
        "        log_error('failed')\n"
        "        raise\n"
    )
    contract = {"must_change": [], "must_not_change": [], "side_effects": [],
                "required_effects": ["add_rollback_on_failure"],
                "retry_semantics": {},
                "rollback_semantics": {"must_rollback_if": ["credit_fails_after_debit"],
                                       "must_not_persist_after_failure": []}}
    r = validate(contract, code, "")
    assert any("compensating" in v.lower() or "ROLLBACK" in v for v in r["violations"])


# ════════════════════════════════════════════════════════════
# DIFF GATE — ORDERING
# ════════════════════════════════════════════════════════════

def test_ordering_correct_after():
    from diff_gate import validate
    code = "line1\ncommit()\nline3\ncache_put(key, val)\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "retry_semantics": {}, "rollback_semantics": {},
                "side_effects": [{"effect": "write_cache", "when": "after", "relative_to": "commit"}]}
    r = validate(contract, code, "")
    assert not any("ORDERING" in v for v in r["violations"])


def test_ordering_reversed():
    from diff_gate import validate
    code = "cache_put(key, val)\nline2\ncommit()\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "retry_semantics": {}, "rollback_semantics": {},
                "side_effects": [{"effect": "write_cache", "when": "after", "relative_to": "commit"}]}
    r = validate(contract, code, "")
    assert any("ORDERING" in v for v in r["violations"])


def test_ordering_alias_resolution():
    from diff_gate import validate
    code = "line1\nsession.commit()\nline3\n_store[key] = val\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "retry_semantics": {}, "rollback_semantics": {},
                "side_effects": [{"effect": "write_cache", "when": "after", "relative_to": "commit"}]}
    r = validate(contract, code, "")
    assert not any("ORDERING" in v for v in r["violations"])


def test_ordering_unresolvable():
    from diff_gate import validate
    code = "do_stuff()\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "retry_semantics": {}, "rollback_semantics": {},
                "side_effects": [{"effect": "write_cache", "when": "after", "relative_to": "unknown_op_xyz"}]}
    r = validate(contract, code, "")
    # Unresolvable is NOT a violation
    ordering_violations = [v for v in r["violations"] if "ORDERING" in v]
    # write_cache not found is a violation, but unknown_op_xyz not found is not
    assert not any("unknown_op_xyz" in v for v in r["violations"])


# ════════════════════════════════════════════════════════════
# DIFF GATE — RETRY SAFETY
# ════════════════════════════════════════════════════════════

def test_forbidden_unguarded_in_loop():
    from diff_gate import validate
    code = "for attempt in range(3):\n    charge_card(amount)\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "side_effects": [], "rollback_semantics": {},
                "retry_semantics": {"duplicate_effects_forbidden": ["charge_card"]}}
    r = validate(contract, code, "")
    assert any("RETRY_SAFETY" in v for v in r["violations"])


def test_forbidden_guarded_in_loop():
    from diff_gate import validate
    code = "for attempt in range(3):\n    if not already_charged:\n        charge_card(amount)\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "side_effects": [], "rollback_semantics": {},
                "retry_semantics": {"duplicate_effects_forbidden": ["charge_card"]}}
    r = validate(contract, code, "")
    assert not any("RETRY_SAFETY" in v for v in r["violations"])


def test_forbidden_outside_loop():
    from diff_gate import validate
    code = "charge_card(amount)\nlog_result()\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "side_effects": [], "rollback_semantics": {},
                "retry_semantics": {"duplicate_effects_forbidden": ["charge_card"]}}
    r = validate(contract, code, "")
    assert not any("RETRY_SAFETY" in v for v in r["violations"])


# ════════════════════════════════════════════════════════════
# DIFF GATE — ROLLBACK
# ════════════════════════════════════════════════════════════

def test_rollback_try_except_restore():
    from diff_gate import validate
    code = "a = 100\ntry:\n    a -= 50\n    do_something()\nexcept:\n    a += 50\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "side_effects": [], "retry_semantics": {},
                "rollback_semantics": {"must_rollback_if": ["something_fails_after_debit"],
                                       "must_not_persist_after_failure": []}}
    r = validate(contract, code, "")
    rollback_v = [v for v in r["violations"] if "ROLLBACK" in v]
    assert len(rollback_v) == 0


def test_rollback_naked_operation():
    from diff_gate import validate
    code = "balance -= amount\ncredit(receiver, amount)\n"
    contract = {"must_change": [], "must_not_change": [],
                "required_effects": [], "side_effects": [], "retry_semantics": {},
                "rollback_semantics": {"must_rollback_if": [],
                                       "must_not_persist_after_failure": ["balance_decrement"]}}
    r = validate(contract, code, "")
    assert any("persist after failure" in v.lower() for v in r["violations"])


# ════════════════════════════════════════════════════════════
# CONTRACT VERIFIABLE
# ════════════════════════════════════════════════════════════

def test_verifiable_all_known():
    from contract import parse_contract
    raw = json.dumps({
        "root_cause": "bug", "must_change": ["f::g"], "must_not_change": [],
        "required_effects": ["add_rollback_on_failure", "introduce_idempotency_guard"],
    })
    c = parse_contract(raw)
    assert c["_verifiable"] is True


def test_not_verifiable_unknown_effect():
    from contract import parse_contract
    raw = json.dumps({
        "root_cause": "bug", "must_change": [], "must_not_change": [],
        "required_effects": ["add_rollback_on_failure", "invent_new_paradigm"],
    })
    c = parse_contract(raw)
    assert c["_verifiable"] is False


def test_not_verifiable_bad_ordering():
    from contract import parse_contract
    raw = json.dumps({
        "root_cause": "bug", "must_change": [], "must_not_change": [],
        "required_effects": [],
        "side_effects": [{"effect": "x", "when": "sideways"}],
    })
    c = parse_contract(raw)
    assert c["_verifiable"] is False


# ════════════════════════════════════════════════════════════
# INTEGRATION
# ════════════════════════════════════════════════════════════

def test_condition_registered():
    from runner import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS
    assert "contract_gated" in ALL_CONDITIONS
    assert "contract_gated" in VALID_CONDITIONS
    assert "CG" == COND_LABELS["contract_gated"]


def test_full_flow_mock():
    """Run contract_gated on a case in mock mode — verify result structure."""
    from execution import run_contract_gated
    from runner import load_cases
    case = load_cases(case_id="l3_state_pipeline")[0]
    cid, cond, ev = run_contract_gated(case, "gpt-4.1-nano")
    assert cid == "l3_state_pipeline"
    assert cond == "contract_gated"
    assert "pass" in ev
    assert "score" in ev
    assert "contract_satisfied" in ev
    assert "contract_verifiable" in ev
    assert "gate_results" in ev
    assert "num_attempts" in ev
    assert isinstance(ev["gate_results"], list)


def test_no_regression_baseline():
    """Baseline still works after CGE addition."""
    from execution import run_single
    from runner import load_cases
    case = load_cases(case_id="l3_state_pipeline")[0]
    cid, cond, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "pass" in ev
    assert "score" in ev


# ════════════════════════════════════════════════════════════
# RUNNER
# ════════════════════════════════════════════════════════════

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
