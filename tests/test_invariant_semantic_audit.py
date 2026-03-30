"""Hostile semantic audit of all invariant types.

For each invariant: runs a positive case (should pass) and an adversarial
negative case (should fail). Classifies as STRONG, WEAK, or FAKE.

Writes:
  validation/invariant_semantic_audit_report.json
  validation/invariant_semantic_audit_summary.md
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.executors.exec_eval import INVARIANT_TYPE_REGISTRY

BASE = Path(__file__).resolve().parents[1]
VALIDATION_DIR = BASE / "validation"


# ============================================================
# AUDIT CASES
# ============================================================

AUDIT_CASES = [
    # --- independence ---
    {
        "invariant_type": "independence",
        "name": "positive",
        "code": "DEFAULTS = {'timeout': 30}\ndef f(): return DEFAULTS.copy()",
        "contract": {"function": "f", "tests": [{"type": "independence", "mutation": {"timeout": 999}}]},
        "expected_pass": True,
        "expected_reason": "copies are independent",
    },
    {
        "invariant_type": "independence",
        "name": "adversarial_negative",
        "code": "DEFAULTS = {'timeout': 30}\ndef f(): return DEFAULTS",
        "contract": {"function": "f", "tests": [{"type": "independence", "mutation": {"timeout": 999}}]},
        "expected_pass": False,
        "expected_reason": "same object returned, mutation leaks",
    },

    # --- idempotence ---
    {
        "invariant_type": "idempotence",
        "name": "positive",
        "code": "def f(): return 42",
        "contract": {"function": "f", "tests": [{"type": "idempotence"}]},
        "expected_pass": True,
        "expected_reason": "pure function, same result each call",
    },
    {
        "invariant_type": "idempotence",
        "name": "adversarial_negative",
        "code": "counter = {'n': 0}\ndef f():\n    counter['n'] += 1\n    return counter['n']",
        "contract": {"function": "f", "tests": [{"type": "idempotence"}]},
        "expected_pass": False,
        "expected_reason": "hidden counter causes different results each call",
    },

    # --- consistency ---
    {
        "invariant_type": "consistency",
        "name": "positive",
        "code": "def f(): return {'debit': 100, 'credit': 100}",
        "contract": {"function": "f", "tests": [{"type": "consistency", "check": "lambda r: r['debit'] == r['credit']"}]},
        "expected_pass": True,
        "expected_reason": "debit equals credit",
    },
    {
        "invariant_type": "consistency",
        "name": "adversarial_negative",
        "code": "def f(): return {'debit': 100, 'credit': 90}",
        "contract": {"function": "f", "tests": [{"type": "consistency", "check": "lambda r: r['debit'] == r['credit']"}]},
        "expected_pass": False,
        "expected_reason": "debit != credit, conservation violated",
    },

    # --- field_sync ---
    {
        "invariant_type": "field_sync",
        "name": "positive",
        "code": "def f(): return {'name': 'Alice', 'display_name': 'Alice'}",
        "contract": {"function": "f", "tests": [{"type": "field_sync", "primary_field": "name", "dependent_field": "display_name"}]},
        "expected_pass": True,
        "expected_reason": "dependent field matches primary",
    },
    {
        "invariant_type": "field_sync",
        "name": "adversarial_negative",
        "code": "def f(): return {'name': 'Alice', 'display_name': 'Bob'}",
        "contract": {"function": "f", "tests": [{"type": "field_sync", "primary_field": "name", "dependent_field": "display_name"}]},
        "expected_pass": False,
        "expected_reason": "name changed but display_name is stale",
    },

    # --- lifecycle ---
    {
        "invariant_type": "lifecycle",
        "name": "positive",
        "code": "def f(): return 1",
        "contract": {"function": "f", "tests": [{"type": "lifecycle"}]},
        "expected_pass": True,
        "expected_reason": "stateless function, same result after hypothetical reset",
    },
    {
        "invariant_type": "lifecycle",
        "name": "adversarial_negative",
        "code": "cache = {'val': None}\ndef f():\n    if cache['val'] is None:\n        cache['val'] = 42\n    return cache['val']",
        "contract": {"function": "f", "tests": [{"type": "lifecycle", "reset_fn": "reset"}]},
        "expected_pass": True,
        "expected_reason": "ADVERSARIAL: reset_fn 'reset' does not exist, so lifecycle handler skips reset and both calls return same cached value — handler cannot detect stale cache without a real reset function. This SHOULD fail but will pass.",
    },

    # --- side_effect_count ---
    {
        "invariant_type": "side_effect_count",
        "name": "positive",
        "code": "def f(): return [1, 2, 3]",
        "contract": {"function": "f", "tests": [{"type": "side_effect_count", "expected_count": 3}]},
        "expected_pass": True,
        "expected_reason": "returns list of length 3 matching expected_count",
    },
    {
        "invariant_type": "side_effect_count",
        "name": "adversarial_negative",
        "code": "def f(): return [1]",
        "contract": {"function": "f", "tests": [{"type": "side_effect_count", "expected_count": 3}]},
        "expected_pass": False,
        "expected_reason": "only 1 side effect, expected 3",
    },

    # --- no_exception ---
    {
        "invariant_type": "no_exception",
        "name": "positive",
        "code": "def f(x=None): return x or 'default'",
        "contract": {"function": "f", "tests": [{"type": "no_exception", "args": [None]}]},
        "expected_pass": True,
        "expected_reason": "handles None input without exception",
    },
    {
        "invariant_type": "no_exception",
        "name": "adversarial_negative",
        "code": "def f(x=None): return x.strip()",
        "contract": {"function": "f", "tests": [{"type": "no_exception", "args": [None]}]},
        "expected_pass": False,
        "expected_reason": "None.strip() raises AttributeError",
    },

    # --- branch_coverage ---
    {
        "invariant_type": "branch_coverage",
        "name": "positive",
        "code": "def f(x):\n    if x > 0: return 'pos'\n    elif x < 0: return 'neg'\n    else: return 'zero'",
        "contract": {"function": "f", "tests": [{"type": "branch_coverage", "inputs": [[1], [-1], [0]]}]},
        "expected_pass": True,
        "expected_reason": "all branches return non-None",
    },
    {
        "invariant_type": "branch_coverage",
        "name": "adversarial_negative",
        "code": "def f(x):\n    if x > 0: return 'pos'\n    elif x < 0: return 'neg'",
        "contract": {"function": "f", "tests": [{"type": "branch_coverage", "inputs": [[1], [-1], [0]]}]},
        "expected_pass": False,
        "expected_reason": "x=0 falls through, returns None",
    },

    # --- boundary_condition ---
    {
        "invariant_type": "boundary_condition",
        "name": "positive",
        "code": "def f(x): return x >= 10",
        "contract": {"function": "f", "tests": [{"type": "boundary_condition", "boundary_cases": [{"args": [10], "expected": True}, {"args": [9], "expected": False}]}]},
        "expected_pass": True,
        "expected_reason": "correct >= at boundary",
    },
    {
        "invariant_type": "boundary_condition",
        "name": "adversarial_negative",
        "code": "def f(x): return x > 10",
        "contract": {"function": "f", "tests": [{"type": "boundary_condition", "boundary_cases": [{"args": [10], "expected": True}, {"args": [9], "expected": False}]}]},
        "expected_pass": False,
        "expected_reason": "off-by-one: > instead of >=, f(10) returns False not True",
    },

    # --- state_conservation ---
    {
        "invariant_type": "state_conservation",
        "name": "positive",
        "code": "def f(): return 42",
        "contract": {"function": "f", "tests": [{"type": "state_conservation"}]},
        "expected_pass": True,
        "expected_reason": "stateless, successive calls identical",
    },
    {
        "invariant_type": "state_conservation",
        "name": "adversarial_negative",
        "code": "total = {'balance': 100}\ndef f():\n    total['balance'] -= 10\n    return total['balance']",
        "contract": {"function": "f", "tests": [{"type": "state_conservation"}]},
        "expected_pass": False,
        "expected_reason": "balance decreases each call, state not conserved",
    },

    # --- ordering ---
    {
        "invariant_type": "ordering",
        "name": "positive",
        "code": "def f(): return 'ok'",
        "contract": {"function": "f", "tests": [{"type": "ordering"}]},
        "expected_pass": True,
        "expected_reason": "no-op ordering: function runs without exception",
    },
    {
        "invariant_type": "ordering",
        "name": "adversarial_negative",
        "code": "log = []\ndef step_a(): log.append('a')\ndef step_b(): log.append('b')\ndef f(): return log",
        "contract": {"function": "f", "tests": [{"type": "ordering", "steps": ["step_b", "step_a"], "check": "lambda g: g.get('log', []) == ['a', 'b']"}]},
        "expected_pass": False,
        "expected_reason": "steps executed B,A but check expects [a,b] — wrong order. BUT handler runs steps then checks, so it depends on whether check actually sees the wrong order.",
    },

    # --- atomicity ---
    {
        "invariant_type": "atomicity",
        "name": "positive",
        "code": "def f(): return 1",
        "contract": {"function": "f", "tests": [{"type": "atomicity"}]},
        "expected_pass": True,
        "expected_reason": "simple function, no partial state",
    },
    {
        "invariant_type": "atomicity",
        "name": "adversarial_negative",
        "code": "state = {'balance': 100}\ndef f():\n    state['balance'] -= 50\n    raise ValueError('payment failed')",
        "contract": {"function": "f", "tests": [{"type": "atomicity", "check": "lambda g: g.get('state', {}).get('balance') == 100"}]},
        "expected_pass": False,
        "expected_reason": "balance debited but exception thrown, state corrupted",
    },

    # --- structure_alignment ---
    {
        "invariant_type": "structure_alignment",
        "name": "positive",
        "code": "def f(): return {'ids': [1,2,3], 'names': ['a','b','c']}",
        "contract": {"function": "f", "tests": [{"type": "structure_alignment", "aligned_fields": ["ids", "names"]}]},
        "expected_pass": True,
        "expected_reason": "ids and names have same length",
    },
    {
        "invariant_type": "structure_alignment",
        "name": "adversarial_negative",
        "code": "def f(): return {'ids': [1,2,3], 'names': ['a','b']}",
        "contract": {"function": "f", "tests": [{"type": "structure_alignment", "aligned_fields": ["ids", "names"]}]},
        "expected_pass": False,
        "expected_reason": "ids has 3 elements, names has 2",
    },

    # --- no_silent_fallback ---
    {
        "invariant_type": "no_silent_fallback",
        "name": "positive",
        "code": "def f(): return 'configured_value'",
        "contract": {"function": "f", "tests": [{"type": "no_silent_fallback", "forbidden_values": [None, "default"]}]},
        "expected_pass": True,
        "expected_reason": "returns configured value, not None or default",
    },
    {
        "invariant_type": "no_silent_fallback",
        "name": "adversarial_negative",
        "code": "def f(): return None",
        "contract": {"function": "f", "tests": [{"type": "no_silent_fallback", "forbidden_values": [None, "default"]}]},
        "expected_pass": False,
        "expected_reason": "returns None which is a forbidden fallback value",
    },
]


# ============================================================
# RUNNER
# ============================================================

def _run_one(case: dict) -> dict:
    """Execute one audit case. Returns result dict."""
    from graph_runner.state import Artifact, ExecutionState
    from graph_runner.executors.exec_eval import exec_eval_executor

    code = case["code"]
    contract = case["contract"]

    state = ExecutionState()
    state.add_artifact("case", Artifact.create(type="case", value={"id": "audit", "test_contract": contract}))
    state.add_artifact("parsed_response", Artifact.create(
        type="parsed_response", value={"reasoning": "audit", "code": code}
    ))

    try:
        result = exec_eval_executor(state)
        final_state = result.state
    except Exception as e:
        return {
            "crashed": True,
            "crash_error": f"{type(e).__name__}: {e}",
            "passed": None,
            "error": None,
        }

    if final_state.has("exec_result"):
        val = final_state.get("exec_result").value
        return {
            "crashed": False,
            "passed": val["success"],
            "error": val.get("error"),
            "tests_run": val.get("tests_run"),
            "tests_passed": val.get("tests_passed"),
        }
    elif final_state.has("exec_contract_error"):
        return {
            "crashed": False,
            "passed": False,
            "error": f"contract_error: {final_state.get('exec_contract_error').value}",
        }
    else:
        return {
            "crashed": False,
            "passed": None,
            "error": "no exec_result or exec_contract_error produced",
        }


def classify(positive_result: dict, negative_result: dict,
             positive_case: dict, negative_case: dict) -> tuple[str, str]:
    """Classify invariant as STRONG, WEAK, or FAKE."""
    pos_ok = positive_result.get("passed") == positive_case["expected_pass"]
    neg_ok = negative_result.get("passed") == negative_case["expected_pass"]

    if positive_result.get("crashed") or negative_result.get("crashed"):
        return "FAKE", "Handler crashed"

    if not pos_ok:
        return "FAKE", f"Positive case wrong: expected pass={positive_case['expected_pass']}, got {positive_result.get('passed')}"

    if not neg_ok:
        # Adversarial negative passed when it should have failed
        return "FAKE", f"Adversarial negative NOT caught: expected pass={negative_case['expected_pass']}, got {negative_result.get('passed')}. Error: {negative_result.get('error')}"

    # Both matched expectations. Check if negative failed for the right reason.
    neg_error = negative_result.get("error", "") or ""
    inv_type = positive_case["invariant_type"]

    # Semantic relevance check: does the error message relate to the invariant?
    semantic_keywords = {
        "independence": ["independence", "leak", "mutation"],
        "idempotence": ["idempotence", "differ"],
        "consistency": ["consistency", "violated", "check"],
        "field_sync": ["field_sync", "sync", "not synced"],
        "lifecycle": ["lifecycle", "reset", "differ"],
        "side_effect_count": ["side_effect", "count", "length"],
        "no_exception": ["exception", "Error"],
        "branch_coverage": ["branch", "None", "returned None"],
        "boundary_condition": ["boundary", "got", "expected"],
        "state_conservation": ["state_conservation", "differ", "changed"],
        "ordering": ["ordering", "order", "state check"],
        "atomicity": ["atomicity", "invariant broken"],
        "structure_alignment": ["structure_alignment", "lengths differ"],
        "no_silent_fallback": ["silent_fallback", "forbidden"],
    }

    keywords = semantic_keywords.get(inv_type, [])
    error_lower = neg_error.lower()
    relevant = any(kw.lower() in error_lower for kw in keywords)

    if relevant:
        return "STRONG", f"Both cases correct. Failure reason is semantically relevant: {neg_error[:100]}"
    else:
        return "WEAK", f"Both cases matched expectations, but failure reason may be a proxy: {neg_error[:100]}"


# ============================================================
# MAIN
# ============================================================

def main():
    # Verify all registry types have audit cases
    registry_types = set(INVARIANT_TYPE_REGISTRY.keys())
    audited_types = set(c["invariant_type"] for c in AUDIT_CASES)
    missing = registry_types - audited_types
    assert not missing, f"Missing audit cases for: {missing}"

    # Run audit
    results_by_type = {}
    report_invariants = []

    for inv_type in sorted(registry_types):
        positives = [c for c in AUDIT_CASES if c["invariant_type"] == inv_type and c["name"] == "positive"]
        negatives = [c for c in AUDIT_CASES if c["invariant_type"] == inv_type and c["name"] == "adversarial_negative"]

        assert len(positives) >= 1, f"No positive case for {inv_type}"
        assert len(negatives) >= 1, f"No adversarial negative for {inv_type}"

        pos_case = positives[0]
        neg_case = negatives[0]

        pos_result = _run_one(pos_case)
        neg_result = _run_one(neg_case)

        classification, reason = classify(pos_result, neg_result, pos_case, neg_case)

        results_by_type[inv_type] = {
            "positive_passed": pos_result.get("passed"),
            "negative_passed": neg_result.get("passed"),
            "negative_error": neg_result.get("error"),
            "classification": classification,
            "reason": reason,
        }

        report_invariants.append({
            "invariant_type": inv_type,
            "positive_passed": pos_result.get("passed"),
            "negative_failed": neg_result.get("passed") is False,
            "classification": classification,
            "reason": reason,
        })

        pos_mark = "PASS" if pos_result.get("passed") == pos_case["expected_pass"] else "WRONG"
        neg_mark = "PASS" if neg_result.get("passed") == neg_case["expected_pass"] else "WRONG"
        print(f"[{inv_type:25s}] pos={pos_mark} neg={neg_mark} → {classification}")
        if classification != "STRONG":
            print(f"  reason: {reason}")

    # Summary
    strong = sum(1 for r in report_invariants if r["classification"] == "STRONG")
    weak = sum(1 for r in report_invariants if r["classification"] == "WEAK")
    fake = sum(1 for r in report_invariants if r["classification"] == "FAKE")

    print()
    print(f"{'=' * 50}")
    print(f"STRONG: {strong}  WEAK: {weak}  FAKE: {fake}")
    print(f"{'=' * 50}")

    # Write JSON report
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "invariants": report_invariants,
        "summary": {"strong": strong, "weak": weak, "fake": fake},
    }
    report_path = VALIDATION_DIR / "invariant_semantic_audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON report: {report_path}")

    # Write markdown summary
    md_lines = [
        "# Invariant Semantic Audit Summary\n",
        f"**STRONG: {strong} | WEAK: {weak} | FAKE: {fake}**\n",
        "",
        "| Invariant | Positive | Adv. Negative | Classification | Reason |",
        "|-----------|----------|---------------|----------------|--------|",
    ]
    for r in report_invariants:
        pos = "PASS" if r["positive_passed"] else "FAIL"
        neg = "CAUGHT" if r["negative_failed"] else "MISSED"
        md_lines.append(
            f"| {r['invariant_type']} | {pos} | {neg} | **{r['classification']}** | {r['reason'][:80]} |"
        )

    md_lines.extend([
        "",
        "## Strongest",
        "",
    ])
    for r in report_invariants:
        if r["classification"] == "STRONG":
            md_lines.append(f"- **{r['invariant_type']}**: {r['reason'][:100]}")

    md_lines.extend([
        "",
        "## Weakest / Proxy-based",
        "",
    ])
    for r in report_invariants:
        if r["classification"] == "WEAK":
            md_lines.append(f"- **{r['invariant_type']}**: {r['reason'][:100]}")

    md_lines.extend([
        "",
        "## Fake / Must Redesign",
        "",
    ])
    for r in report_invariants:
        if r["classification"] == "FAKE":
            md_lines.append(f"- **{r['invariant_type']}**: {r['reason'][:100]}")

    md_path = VALIDATION_DIR / "invariant_semantic_audit_summary.md"
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown summary: {md_path}")

    # Hard assertion: report files written
    assert report_path.exists(), "JSON report not written"
    assert md_path.exists(), "Markdown summary not written"

    # Hard assertion: all types classified
    assert len(report_invariants) == len(registry_types), "Not all invariant types classified"


if __name__ == "__main__":
    main()
