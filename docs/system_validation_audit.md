# System Validation Audit — Adversarial Assessment

**Date:** 2026-03-28
**Auditor:** Claude (hostile internal auditor mode)
**Verdict:** The oracle is OPERATIONALLY SOUND but the surrounding system has SIGNIFICANT gaps in metadata integrity, mutation coverage, and architectural isolation.

---

## SECTION 1 — EXECUTIVE SUMMARY

### What is solid
- **The oracle itself (tests_v2/ + exec_evaluate)** is the real deal. All 58 cases have behavioral tests. The tests are structurally correct for the invariants they check. `validate_cases_v2.py` proves every test fails on buggy code and passes on reference fix.
- **The execution pipeline** always calls `exec_evaluate()`. There is no code path where a pass/fail is assigned without running the test. The oracle is AUTHORITATIVE.
- **The 5-gate mutation validation** has zero false acceptances across 219 variants.

### What is shaky
- **10 cases have metadata misalignment** between `reference_fix.function` and what the test actually exercises. 2 of these (async_race_lock, commit_gate) can cause FALSE FAILs via the rename_error path in multi-file assembly.
- **wrong_condition_b mutation gap** is caused by the mutation system trying comparison flips when the actual bug is boolean operator swap (`or` vs `and`). The oracle is correct; the mutation operator is wrong.
- **The graph_runner invariant system is COMPLETELY DISCONNECTED** from the real oracle. It has its own `exec_eval_executor` with toy invariants that don't use `tests_v2/` at all.

### What is misleading
- **The graph_runner's invariant engine** gives the appearance of a working evaluation system, but it operates in a completely different universe from the real benchmark. If you run the graph_runner, you get results that have NO relationship to the real oracle's pass/fail.
- **The AASAT system does not exist.** There is no code, no file, no function named AASAT anywhere in the codebase. Any reference to AASAT in planning documents is aspirational, not operational.

### Biggest risks
1. False FAILs on multi-file cases due to metadata bugs (costs money, produces wrong data)
2. Graph_runner appearing to work while being disconnected from truth
3. No metadata validation check in the pipeline
4. Mutation system has a blind spot for boolean operator bugs

---

## SECTION 2 — CHECK INVENTORY

| Check | Location | Triggers | Gates? | Authoritative? |
|-------|----------|----------|--------|----------------|
| `exec_evaluate()` | `exec_eval.py:800` | Every eval call | YES — determines pass/fail | YES |
| `preflight_verify_tests()` | `runner.py:143` | Before any run | YES — blocks run if tests missing | YES |
| `validate_run()` | `condition_registry.py` | Before any run | YES — blocks incompatible case/condition pairs | YES |
| `_validate_experiment_config()` | `runner.py:365` | Before ablation | YES — blocks degenerate configs | YES |
| `_validate_execution_sanity()` | `runner.py:397` | After ablation run | YES — blocks if ran_rate < 50% | YES |
| `validate_cases_v2.py` | Standalone script | Manual invocation | NO — advisory only, not in run path | NO |
| Cost protection gate | `run_ablation_leg_8t.sh:68` | Before full ablation | YES — blocks if canary fails | PARTIAL (only 1 case) |
| `ResponseContract.validate()` | `graph_runner/contracts/` | Graph_runner only | YES (within graph_runner) | NO (disconnected from real oracle) |
| `ExecutionContract.validate()` | `graph_runner/contracts/` | Graph_runner only | YES (within graph_runner) | NO (disconnected from real oracle) |
| Mutation engine 5-gate | `scripts/mutation_engine.py` | Variant generation | YES — rejects invalid variants | YES (uses real exec_evaluate) |

---

## SECTION 3 — PATH AUDIT

### Path 1: Ablation run (production path)

```
run_ablation_leg_8t.sh
  → evaluator sanity check (exec_evaluate on alias_config_a reference fix)
  → gate run (5 cases × 2 conditions, real LLM calls)
  → validate_smoke.py (check events: passes > 0, ran_rate ≥ 50%)
  → 24 workers, each calls runner.py --run-dir
    → preflight_verify_tests (all cases have test functions)
    → validate_run (case/condition compatibility)
    → _validate_experiment_config (config sanity)
    → run_all → for each case:
      → build_prompt → call_model → parse_model_response → reconstruct
      → evaluate_output → exec_evaluate (THE ORACLE)
      → llm_classify (advisory only, UNRELIABLE)
    → _validate_execution_sanity (post-run: ran_rate, pass_rate checks)
```

**Checks that run:** All 7 production checks.
**Checks NOT invoked:** `validate_cases_v2.py` (manual only), graph_runner (separate system).
**Risk:** Metadata bugs silently cause rename_error on 2 multi-file cases.

### Path 2: Single-case run (debugging)

```
runner.py --model X --case-id Y --cases cases_v2.json --conditions baseline
  → preflight_verify_tests
  → validate_run
  → run_all → evaluate_output → exec_evaluate
```

**Same oracle, fewer guards.** No cost protection gate, no execution sanity check.

### Path 3: Mutation variant validation

```
generate_buggy_variants_v2.py
  → for each case:
    → load_reference_code (merge fix with originals)
    → for each operator:
      → find_targets (AST)
      → mutate (AST transform)
      → verify_diff
      → check_semantic_guardrails
      → validate_with_oracle → exec_evaluate (SAME ORACLE)
```

**Uses the real oracle.** If oracle has a false negative, mutation system inherits it.

### Path 4: Graph_runner (NEW, DISCONNECTED)

```
graph_runner/graph_runner.py
  → build_prompt_executor → generate_executor → parse_executor → exec_eval_executor
  → exec_eval_executor uses its OWN invariant engine
  → NEVER calls exec_evaluate from exec_eval.py
  → NEVER loads tests from tests_v2/
  → NEVER uses _load_v2_test or _CASE_TESTS
```

**COMPLETELY DISCONNECTED from real oracle.** The graph_runner's exec_eval_executor has hand-written invariant dispatchers (`_run_independence_test`, `_run_idempotence_test`, etc.) that are NOT the same tests as `tests_v2/`.

### Path 5: validate_cases_v2.py (manual preflight)

```
python validate_cases_v2.py
  → for each case:
    → check_loads (buggy code compiles)
    → check_fails_buggy (test rejects buggy code)
    → check_passes_fixed (test accepts reference fix)
    → check_minimal (diff is small)
    → check_idempotent (test is deterministic)
```

**NOT in the automated run path.** Must be invoked manually. Does NOT check metadata alignment.

---

## SECTION 4 — ORACLE / tests_v2 AUDIT

### Family-by-family assessment

| Family | Test file | Tests real invariant? | Boundary coverage | Weakness |
|--------|-----------|----------------------|-------------------|----------|
| alias_config | test_alias_config.py | YES — mutation leakage test | STRONG (mutates cfg1, checks cfg2) | None found |
| mutable_default | test_mutable_default.py | YES — cross-call state leakage | STRONG (two calls, check independence) | None found |
| stale_cache | test_stale_cache.py | YES — update then read | STRONG (add → update → get) | None found |
| partial_update | test_partial_update.py | YES — dependent field sync | STRONG (change name, check display_name) | None found |
| early_return | test_early_return.py | YES — ledger completeness | STRONG (zero-amount path) | None found |
| wrong_condition | test_wrong_condition.py | YES — all 3 levels correct | test_a: boundary (count==limit), test_b: boolean logic, test_c: precedence | **test_b tests `or` vs `and`, NOT comparison operators** — mutation system targets wrong bug type |
| missing_branch | test_missing_branch.py | YES — dispatch table completeness | MODERATE | Depends on which role is tested |
| partial_rollback | test_partial_rollback.py | YES — stock restoration | STRONG | None found |
| lazy_init | test_lazy_init.py | YES — reset propagation | STRONG | None found |
| silent_default | test_silent_default.py | YES — configured vs default | STRONG | None found |
| index_misalign | test_index_misalign.py | YES — parallel array alignment | STRONG | None found |
| temporal_drift | test_temporal_drift.py | YES — raw stats vs transformed | STRONG | None found |

### Oracle sensitivity gaps

1. **wrong_condition_b**: The oracle IS correct (tests `or` vs `and`). Our mutation system was wrong — it tried comparison flips instead of boolean operator swaps. This is a MUTATION SYSTEM BUG, not an oracle gap.

2. **Boundary cases in multi-file assembly**: When a model provides partial code, the assembly prepends originals. A model that fixes function A but leaves buggy function B untouched will pass if the test only exercises function A. This is BY DESIGN (the test tests what it tests) but could miss incomplete fixes.

---

## SECTION 5 — AASAT AUDIT

**AASAT does not exist.** No code, no files, no functions, no imports anywhere in the codebase reference AASAT. Any planning documents that mention AASAT are aspirational. If AASAT were removed, nothing would change because there is nothing to remove.

---

## SECTION 6 — GRAPH / INVARIANT SYSTEM AUDIT

### What exists
- `graph_runner/executors/exec_eval.py` — an invariant engine with 14+ dispatchers
- `graph_runner/contracts/` — ResponseContract, ExecutionContract
- `graph_runner/graph_factory.py` — 4-stage pipeline (build_prompt → generate → parse → exec_eval)
- `tests/test_invariant_engine.py`, `test_invariant_types.py`, `test_invariant_coverage.py`
- The invariant semantic audit (`validation/invariant_semantic_audit_report.json`) — 12 STRONG, 1 WEAK, 1 FAKE

### What is disconnected
**EVERYTHING.** The graph_runner's exec_eval_executor:
- Does NOT import `exec_eval.py` (the real evaluator)
- Does NOT import `tests_v2/` test functions
- Does NOT use `_load_v2_test()`
- Has its OWN invariant implementations that are DIFFERENT from the real tests
- Uses `test_contract` from case metadata (human-readable, not machine-executable) and falls back to a generic "find callable, call it" mode

**Concrete example:**
- Real oracle for `alias_config_a`: `tests_v2/test_alias_config.py:test_a(mod)` — calls `create_config({"timeout": 5})` then `create_config()`, checks `cfg2.get("timeout") != 30`, checks `DEFAULTS` not corrupted
- Graph runner for `alias_config_a`: `_run_independence_test(fn, test)` — calls `fn()` twice, mutates first result, checks second unchanged
- These test the SAME invariant but with DIFFERENT inputs and DIFFERENT assertions

### Architectural gap
The graph_runner needs to either:
1. Import and use the real `tests_v2/` test functions (recommended)
2. Or prove its own invariant engine produces identical pass/fail results on all 58 cases

Currently neither is true.

---

## SECTION 7 — GAP TABLE

| Component | Expected | Actual | Severity | Fix |
|-----------|----------|--------|----------|-----|
| `reference_fix.function` metadata | Matches test target | 10 cases mismatched | HIGH (2 can cause false FAIL) | Fix metadata |
| Metadata validation check | Exists in pipeline | MISSING | HIGH | Add to validate_cases_v2.py |
| Graph_runner oracle | Uses real tests_v2 | Uses toy invariants | HIGH | Wire to real oracle |
| AASAT system | Exists and constrains | DOES NOT EXIST | MEDIUM (false confidence in docs) | Remove from plans or implement |
| wrong_condition_b mutation | Boolean swap operator | Comparison flip (wrong type) | MEDIUM | Add `SwapBoolOp` AST operator |
| Cost protection gate | Tests all families | Tests 1 case (alias_config_a) | MEDIUM | Expand to 1 per family |
| validate_cases_v2.py | Runs in CI | Manual only | MEDIUM | Add to Makefile/CI |
| Assembly dep masking | Detected | Not detected | LOW | Hard to fix without redesign |

---

## SECTION 8 — TOP RISKS (ranked)

1. **Graph_runner produces results with no relationship to real oracle** — anyone trusting graph_runner output for benchmark conclusions will get wrong answers
2. **Metadata bugs cause false FAILs on 2 multi-file cases** — wastes money, corrupts data, undermines trust in results
3. **No automated metadata validation** — new cases can be added with wrong metadata and nobody catches it
4. **Mutation system has wrong operator for wrong_condition_b** — needs boolean operator swap, not comparison flip
5. **validate_cases_v2.py not in CI** — the most comprehensive validation script only runs when someone remembers to invoke it
6. **Cost protection gate only tests 1 case** — a family-specific oracle bug would pass the gate
7. **AASAT referenced in plans but doesn't exist** — creates false confidence about system capabilities

---

## SECTION 9 — HARDENING PLAN

### Immediate (1 day)

1. **Fix metadata for 10 mismatched cases** — update `reference_fix.function` in `cases_v2.json` to match what `tests_v2/` actually exercises
2. **Add `SwapBoolOp` mutation operator** — AST transform: `And` → `Or` and vice versa, targeting `wrong_condition_b`
3. **Add metadata validation to `validate_cases_v2.py`** — check 7: verify `reference_fix.function` appears in the test function's code
4. **Add `validate_cases_v2.py` to Makefile** — `make validate` runs it

### Medium-term (1 week)

5. **Wire graph_runner to real oracle** — replace `graph_runner/executors/exec_eval.py` invariant engine with a call to `exec_eval.exec_evaluate()`
6. **Expand cost protection gate** — test 1 case per family (28 cases) instead of just alias_config_a
7. **Remove AASAT references** from all planning documents or implement it

### Architectural (1 month)

8. **Integrate validate_cases_v2.py into runner.py preflight** — run all 6 checks + metadata check before any experiment
9. **Build case-specific mutation operators** — boolean swap, argument swap, statement reordering per family
10. **Resolve graph_runner vs legacy evaluator** — choose one path and deprecate the other

---

## SECTION 10 — APPENDIX: EVIDENCE

### Metadata mismatches (verified)

| Case | `reference_fix.function` | Test actually calls | File |
|------|-------------------------|-------------------|------|
| async_race_lock | `process_item` | `run_verified` | tests_v2/test_async_race_lock.py |
| commit_gate | `process_batch` | `ingest`, `ingest_and_verify` | tests_v2/test_commit_gate.py |
| lazy_init_a/b/c | `get_settings` | `get_host`, `configure` | tests_v2/test_lazy_init.py |
| lost_update | `make_increment_steps` | `sequential_double_increment` | tests_v2/test_lost_update.py |
| check_then_act | `make_withdraw_steps` | `sequential_withdrawals` | tests_v2/test_check_then_act.py |
| ordering_dependency | `process` | `broken_order`, `correct_order` | tests_v2/test_ordering_dependency.py |
| false_fix_deadlock | `make_transfer_b_to_a_steps` | `interleaved_transfers` | tests_v2/test_false_fix_deadlock.py |
| config_shadowing | `DEFAULTS` (invalid) | `run_system_check` | tests_v2/test_config_shadowing.py |

### Graph_runner disconnection (verified)

```python
# graph_runner/executors/exec_eval.py imports:
from graph_runner.state import Artifact, ExecutionState
from graph_runner.stage_spec import StageResult
from graph_runner.contracts.execution_contract import ExecutionContract, ExecutionContractError

# Does NOT import:
# from exec_eval import exec_evaluate     ← the real oracle
# from exec_eval import _load_v2_test     ← the real test loader
```

### wrong_condition_b bug type (verified)

The bug is `return rate_ok or quota_ok` (should be `and`). This is a boolean operator swap, not a comparison operator flip. The mutation system's `FlipComparison` and `RelaxBoundary` operators cannot produce this mutation.

### AASAT non-existence (verified)

```bash
$ grep -rn "aasat\|AASAT" *.py scripts/*.py graph_runner/**/*.py
(no results)
$ find . -name "*aasat*" -o -name "*AASAT*" | grep -v .venv
(no results)
```
