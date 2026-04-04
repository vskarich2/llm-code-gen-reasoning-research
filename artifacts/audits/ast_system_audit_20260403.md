# AST System Audit — 2026-04-03

## PART 1: AST Verification Full Inventory

### Integrated Pipeline Components (USED IN EVALUATION)

| # | File | Purpose | Strength | Used In Pipeline? |
|---|------|---------|----------|-------------------|
| 1 | `core/evaluation/ast_eval.py` | Main AST evaluation entry. `check_ast_patterns()` runs checkers on reconstructed code | **STRONG** — pattern-based invariant checking | **YES** — called by execution_v2.py line 612 |
| 2 | `core/evaluation/ast_checkers.py` | 21 families, 52 cases. Strict + relaxed + anti patterns | **STRONG** — invariant-derived structural patterns | YES — imported by ast_eval.py |
| 3 | `core/evaluation/ast_checker_overrides.py` | V2 fixes for 6 families (early_return, temporal_drift, etc.) | **STRONG** — argument validation, control flow analysis | YES — imported by ast_eval.py |
| 4 | `core/pipeline/reconstructor.py` | Gate 4: `ast.parse()` for syntax validation. Blocks execution on SyntaxError | **WEAK** — syntax only, no semantics | YES — blocks execution path |
| 5 | `core/evaluation/materialize.py` | Extracts ast_status, ast_correct, ast_score from event logs | Diagnostic — reads signals | YES — materializes metrics |
| 6 | `core/pipeline/prompting/metadata.py` | AST validation of Jinja2 condition expressions | Narrow — prompt-layer only | YES — prompt assembly |

### Offline Tools (NOT IN EVALUATION PIPELINE)

| # | File | Purpose | Strength | Verdict |
|---|------|---------|----------|---------|
| 7 | `scripts/ast_phase1/checkers.py` | Source checkers (duplicate of core/evaluation/ast_checkers.py) | STRONG | **DUPLICATE** — scripts copy |
| 8 | `scripts/ast_phase1/checker_fixes.py` | V1 fixes + NOT_AST_MEASURABLE set | STRONG | **DUPLICATE** — scripts copy |
| 9 | `scripts/ast_phase1/checker_fixes_v2.py` | V2 fixes | STRONG | **DUPLICATE** — scripts copy |
| 10 | `scripts/ast_phase1/retro_eval_full.py` | Retrospective eval on oracle logs | Diagnostic | **OFFLINE TOOL** |
| 11 | `scripts/ast_phase1/retro_eval.py` | Earlier retrospective eval | Diagnostic | **OFFLINE TOOL** |
| 12 | `scripts/ast_phase1/validate_specs.py` | Validate specs vs ref fixes/buggy code | Diagnostic | **OFFLINE TOOL** |
| 13 | `scripts/ast_mutator.py` | ~20 AST NodeTransformers for mutation | STRONG for generation | **CASE GENERATION ONLY** |
| 14 | `scripts/mutation_engine.py` | Mutation orchestration | STRONG for generation | **CASE GENERATION ONLY** |

### Verdict Summary

- **6 components** are in the live evaluation pipeline
- **8 components** are offline tools or duplicates
- The AST checker IS integrated into the pipeline as a **non-gating analytical stage**
- The mutation engine is separate (case generation, not evaluation)

---

## PART 2: AST vs Execution Correctness

### Q1: Is AST verification used to determine correctness?
**NO.** Correctness is determined ONLY by test execution (`exec_canonical()` → `harness/run_case.py` → `test_fn(merged)`). AST is a separate analytical signal.

### Q2: Does AST verification ever override execution results?
**NO.** AST runs AFTER execution (line 612 in execution_v2.py, after exec_result is computed). It never modifies execution_category or pass/fail.

### Q3: How is AST used?
**Soft signal / logging.** AST results are stored in `ev["ast_eval"]` and materialized into metrics. They are NOT used for:
- Gating execution
- Modifying pass/fail
- Influencing retry decisions
- Feeding into the classifier

### Q4: Inconsistencies?
**YES — by design.** The entire point of the AST system is to find cases where:
- AST=correct but tests fail → execution fidelity gap (LEG_ast)
- Tests pass but AST=incorrect → lucky fix or alternative fix

These are not bugs; they are the research signal.

---

## PART 3: Invariance Checks

### Where invariants are defined
- `case_data/cases_v2.json` → `ground_truth_bug.invariant` (text description per case)
- `case_data/tests_v2/test_{family}.py` → behavioral test implementations
- `core/harness/invariant_schema.py` → InvariantSpec type with equivalence policy, assertions, etc.
- `core/harness/invariant_validator.py` → 17-constraint pre-experiment gate

### What invariants check
All invariants are **purely runtime behavioral**:
- `test_alias_config.py`: mutation leak detection (cfg2.timeout != 30)
- `test_invariant_partial_fail.py`: balance conservation (sender + receiver = constant)
- `test_use_before_set.py`: stale data detection (r2 != [], count after empty)

### Execution flow
```
runner.py → execution_v2.run_v2() → _reconstruct_and_execute()
  → exec_canonical(case, parsed_gen, recon, config, logger)
    → _materialize_package() → temp dir with pkg/ + harness/
    → _run_subprocess() → python harness/run_case.py
      → import modules → build namespace → resolve test → call test_fn(merged)
      → test returns (passed, reasons)
    → _classify() → execution_category + score
    → return exec_result dict
```

### Relationship to AST
AST and invariants are **complementary, not overlapping**:
- Invariants check behavioral correctness (what the code DOES)
- AST checks structural correctness (what the code LOOKS LIKE)
- They can disagree: correct structure with wrong values (AST=T, exec=F)
- They do NOT conflict: AST never overrides behavioral verdicts

---

## PART 4: Wiring Audit

### What is ACTUALLY used in the pipeline

| Stage | AST used? | Invariant used? |
|-------|-----------|----------------|
| Prompt assembly | No | No |
| Model call | No | No |
| Parsing | No | No |
| Reconstruction | **ast.parse() for syntax** | No |
| Execution | No | **YES — test_fn runs invariant** |
| Classification (LLM) | No | No |
| AST verification | **YES — pattern matching** | No |
| Metric derivation | Reads AST results | Reads exec results |

### UNUSED LOGIC
- `scripts/ast_phase1/` — entire directory is an offline tool, not called by pipeline
- `scripts/ast_mutator.py` — case generation only, not evaluation
- `case_data/validation/` — 5 validation gate scripts, all offline/preflight
- `core/harness/invariant_schema.py` + `invariant_validator.py` — InvariantSpec system exists but is a preflight gate, not runtime

### DEAD CHECKS
- None identified. All pipeline components are actively called.

### MISWIRED LOGIC
- **scripts/ast_phase1/ vs core/evaluation/**: The checkers exist in BOTH locations. The scripts/ versions are the development originals; core/evaluation/ versions are the pipeline-integrated copies. Risk: they could diverge.

---

## PART 5: Validation Directory

### `case_data/validation/` — PREFLIGHT ONLY
Contains 5 validation gates:
1. `cross_distribution.py` — GATE 1: behavioral comparison old vs new prompts
2. `template_equivalence.py` — GATE 2: prompt equivalence across difficulty levels
3. `prompt_snapshot.py` — GATE 3: serialization snapshot regression
4. `assembly_sensitivity.py` — GATE 4: multi-file assembly comparison
5. `e2e_stress.py` — GATE 5: end-to-end stress test with mock LLM

**NONE of these affect experiment results.** They are standalone scripts run manually before/after system changes. They use mock models, not real LLM calls.

### Other validators (MIXED usage)
- `core/pipeline/prompting/validator.py` — **USED** during prompt assembly (inline)
- `core/harness/invariant_validator.py` — **PREFLIGHT** gate (checks invariant specs before experiments)
- `core/pipeline/orchestration/validate_cases_v2.py` — **OFFLINE** case validation tool

---

## PART 6: AST Checker Coverage Table

| Case | AST Check? | Type | Strength | Used? |
|------|------------|------|----------|-------|
| alias_config_a/b/c | YES | copy-on-return | STRONG | YES |
| stale_cache_a/b | YES | invalidation after write | STRONG | YES |
| stale_cache_c | YES | invalidate_local specifically | STRONG | YES |
| mutable_default_a/b | YES | None default + guard | STRONG | YES |
| mutable_default_c | YES | history local + hasattr | STRONG | YES |
| effect_order_a/b/c | YES | call inside loop | STRONG | YES |
| use_before_set_a/b/c | YES | init before conditional | STRONG | YES |
| retry_dup_a/b/c | YES | break in retry loop | STRONG | YES |
| partial_rollback_a/b/c | YES | compensation in except | STRONG | YES |
| partial_update_a/c | YES | dependent field assignments | MEDIUM | YES |
| missing_branch_a/b | YES | module-level dict key count | MEDIUM | YES |
| missing_branch_c | YES | service_account elif | STRONG | YES |
| wrong_condition_a/b/c | YES | operator type | STRONG | YES |
| early_return_a/b/c | YES | audit call on all paths | STRONG (v2) | YES |
| silent_default_b | YES | string literal check | MEDIUM | YES |
| temporal_drift_a/b/c | YES | argument check (v2) | STRONG (v2) | YES |
| lazy_init_a/b/c | YES | lazy access pattern | MEDIUM | YES |
| hidden_dep_multihop | YES | function call substitution | STRONG (v2) | YES |
| invariant_partial_fail | YES | try/except + rollback | STRONG (v2) | YES |
| cache_invalidation_order | YES | invalidation ordering | STRONG (v2) | YES |
| l3_state_pipeline | YES | commit + freeze_view | STRONG | YES |
| commit_gate | YES | commit + freeze_view | STRONG | YES |
| overdetermination | YES | call removal | STRONG | YES |
| async_race_lock | YES | lock structure | MEDIUM | YES |
| index_misalign_a | YES | parallel insert | MEDIUM | YES |
| **partial_update_b** | **NO** | NOT_AST_MEASURABLE | — | — |
| **index_misalign_b/c** | **NO** | NOT_AST_MEASURABLE | — | — |
| **silent_default_a/c** | **NO** | NOT_AST_MEASURABLE | — | — |
| **false_fix_deadlock** | **NO** | NOT_AST_MEASURABLE (lock ordering) | — | — |
| **lost_update** | **NO** | NOT_AST_MEASURABLE (atomicity) | — | — |
| **check_then_act** | **NO** | NOT_AST_MEASURABLE (atomicity) | — | — |
| **ordering_dependency** | **NO** | NOT_AST_MEASURABLE (buffering) | — | — |
| **config_shadowing** | **NO** | NOT_AST_MEASURABLE (literal value) | — | — |
| **feature_flag_drift** | **NO** | NOT_AST_MEASURABLE (multi-path) | — | — |

**Coverage: 47 of 58 cases AST-measurable (81%). 11 excluded with justification.**

---

## PART 7: Deep Dependency Chain Cases

### Current status
- 8 cases exist in `case_data/deep_dependency_chain_cases/cases/`
- They have a `validator.py` (validation harness) and `spec_types.py`
- **NOT integrated with the main 58-case benchmark**
- **No AST checkers exist for them**
- **No entries in cases_v2.json**
- **No tests in tests_v2/**

### What they would require
For cross-module dependency chain cases, AST checkers would need:
- Import chain verification (module A imports from B which imports from C)
- Function call graph analysis (does A.func() call B.func() which calls C.func()?)
- State propagation checks (does change in C propagate through B to A?)

These are beyond the current checker framework's scope (single-function pattern matching). Integration would require a new checker architecture.

---

## PART 8: Gap Analysis

### 1. Missing AST coverage
- 11 cases explicitly excluded (NOT_AST_MEASURABLE) — justified by runtime semantics
- 8 deep_dependency_chain cases — not integrated at all
- 0 cases in the main 58 that should have AST but don't

### 2. Weaknesses
- AST checks syntax + structure, NOT semantics. P(exec_fail | ast_correct) = 13.8% is the measured gap.
- Some relaxed checkers are generous (accept any try/except as compensation pattern)
- Module-level checks (missing_branch_a/b, lazy_init_a) are weaker than function-level
- 2% LUCKY_FIX rate suggests ~2% of AST specs still miss valid alternatives

### 3. Misalignment
- **None between AST and invariants** — they measure different things by design
- **scripts/ vs core/ duplication** — checkers exist in both locations, could diverge
- **NOT_AST_MEASURABLE justifications are sound** — lock ordering, atomicity, literal values genuinely can't be AST-checked

### 4. Wasted infrastructure
- `scripts/ast_phase1/` duplicates `core/evaluation/` — should be consolidated
- `case_data/validation/` gates are useful but not documented in CLAUDE_RULES
- `core/harness/invariant_schema.py` InvariantSpec system is defined but unclear how many cases use it vs raw test functions

---

## PART 9: Final Verdict

### 1. Is AST verification currently critical to the system?
**YES for analysis, NO for evaluation.** AST provides the structural correctness signal that enables the 3-way decomposition (reasoning × structure × execution). Without it, the paper's execution-fidelity-bottleneck claim has no structural basis. But it does not affect pass/fail — that's execution only.

### 2. Does it meaningfully measure reasoning?
**Partially.** AST measures whether the model produced the correct structural transformation — a proxy for structural reasoning. It does NOT measure:
- Why the model chose that structure (mechanism understanding)
- Whether the model's verbal reasoning was correct (that's the oracle)
- Whether the implementation details are correct (that's execution)

The 92.2% agreement between AST and oracle shows they measure closely related but not identical properties.

### 3. What MUST be fixed?
**Priority 1: Consolidate scripts/ast_phase1/ with core/evaluation/.** Two copies of the same checkers is an invariant violation (INV-02: single canonical implementation).

**Priority 2: Document NOT_AST_MEASURABLE justifications in the case schema.** Currently only in a Python set in checker_fixes.py. Should be in cases_v2.json.

**Priority 3: Add deep_dependency_chain integration plan.** These 8 cases exist but have no path to evaluation.

---

## System Integrity Assessment

| Component | Status | Confidence |
|-----------|--------|------------|
| AST evaluation pipeline integration | **CORRECT** — properly wired, non-gating | HIGH |
| AST checker coverage | **81% (47/58)** — 11 exclusions justified | HIGH |
| AST-execution independence | **CORRECT** — AST never overrides execution | HIGH |
| Invariant test coverage | **100% (58/58)** — all cases have tests | HIGH |
| Invariant-AST alignment | **CORRECT** — complementary, not conflicting | HIGH |
| Code duplication (scripts/ vs core/) | **VIOLATION of INV-02** — needs consolidation | MEDIUM |
| Validation gates | **FUNCTIONAL but offline only** | MEDIUM |
| Deep dependency chain integration | **NOT STARTED** — 8 cases orphaned | LOW |
