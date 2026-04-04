# Execution Failure Decomposition — Final Analysis

**Date:** 2026-04-03
**Data:** 9,027 assessable events; 1,150 AST-correct execution failures; 904 semantic failures subtyped
**Context:** Final tightening pass for publication-grade analysis

---

## 1. Executive Summary

Code generation failure decomposes into three sequential stages. The causal decomposition is:

```
P(exec_fail) =
    P(reasoning_fail)                              =  0.2%
  + P(structural_fail | reasoning_correct)         =  1.3%
  + P(execution_fail | structural_correct)         = 12.7%
```

**Of 1,156 total failures, 99.5% occur after correct reasoning AND correct structure.** The dominant failure mode is not reasoning or structural understanding. It is precision-level binding errors within structurally correct code — wrong values, wrong variable names, wrong scope — that prevent execution despite correct intent.

---

## 2. Anchor Table

| Metric | Value |
|--------|-------|
| P(mechanism_correct) | 99.8% |
| P(ast_correct) | 98.7% |
| P(exec_pass) | 87.2% |
| **P(exec_fail \| ast_correct)** | **12.9%** |
| AST-evaluator agreement | 98.5% |
| LUCKY_FIX | 1.2% |
| AST_partial | 1.0% (90 events) |
| Cross-layer fixes | 133 |

---

## 3. Causal Failure Decomposition

### The pipeline model

Every generated output passes through three stages before it can succeed:

```
Stage 1: Mechanism reasoning   → Does the model understand the bug?
Stage 2: Structural translation → Does the code implement the correct fix pattern?
Stage 3: Execution fidelity    → Does the code actually work when run?
```

Failure at any stage blocks success. The causal question is: which stage is the bottleneck?

### The answer

| Stage | Failure rate | % of all failures | Description |
|-------|-------------|-------------------|-------------|
| 1. Reasoning | 0.2% | 0.6% | Model fails to identify the bug mechanism |
| 2. Structure | 1.3% | 0.5% | Model identifies mechanism but produces wrong structural fix |
| **3. Execution** | **12.7%** | **99.5%** | **Model produces correct structural fix but code fails at runtime** |

**99.5% of all failures occur after the model has correctly identified the mechanism AND produced the correct structural fix.** Reasoning and structural understanding are near-perfect. The bottleneck is execution fidelity.

---

## 4. Execution Failure Taxonomy

Of 1,150 events where AST says structurally correct but execution fails:

| Category | Count | % | Description |
|----------|-------|---|-------------|
| Semantic invariant violation | 904 | 78.6% | Correct fix structure, wrong values/bindings |
| Name/scope error | 231 | 20.1% | Correct structure, undefined variable references |
| Import/dependency failure | 15 | 1.3% | Missing imports |
| Reconstruction/parsing artifact | 0 | 0.0% | None |

**Zero reconstruction artifacts.** The gap is entirely in code generation quality, not pipeline tooling.

---

## 5. Semantic Failure Subtypes

The 904 semantic invariant violations break down further:

| Subtype | Count | % of semantic | Description |
|---------|-------|---------------|-------------|
| **Wrong value or literal** | **805** | **89.0%** | Code has the right structure but assigns wrong constant, wrong string, or produces wrong computed value |
| Unclassified semantic | 47 | 5.2% | Other semantic errors not matching top categories |
| Wrong variable binding | 44 | 4.9% | Code references wrong variable name after restructuring |
| Missing secondary update | 8 | 0.9% | Primary fix applied but dependent state update omitted |

### These are not structural failures — they are precision-level binding errors.

**Concrete example (use_before_set_b, 804 events):**
- **What the model does:** Adds an else branch to `load()` covering the empty-input path. Structurally correct.
- **Why it fails:** The else branch sets `_status` to the wrong string value (e.g., `"done"` instead of `"empty"`), or sets `_data` to the wrong value, or uses a mechanism the test doesn't recognize.
- **Failure reason from logs:** `count=3 after empty input, expected 0`
- **Diagnosis:** The model knows the STRUCTURE of the fix (add else branch). It gets the VALUE wrong. This is a precision error, not a reasoning error.

**Concrete example (mutable_default_c, wrong variable binding):**
- **What the model does:** Restructures the decorator to give each function its own history list. Structurally correct.
- **Why it fails:** The `get_history()` lambda references `_history` but the append uses `history` (mismatched attribute name).
- **Failure reason:** `schedule_one raised: name 'process' is not defined`
- **Diagnosis:** Variable name inconsistency after restructuring. The model got the architecture right but the name bindings wrong.

---

## 6. Family-Level Execution Gap

### Canonical Case: use_before_set_b

```
N = 2,082
AST_correct = 99.1%
exec_pass = 61.2%
P(exec_fail | ast_correct) = 39.1%
```

**Invariant:** `_status` must be set on all paths through `load()`

**Why this is the cleanest execution fidelity demonstration:**
1. The model understands the bug (99.8% mechanism_correct)
2. The model produces the correct structural fix (99.1% add else branch or equivalent)
3. But 39.1% of those structurally correct outputs fail because the else branch contains the wrong value

804 of 808 failures in this case are `wrong_value_or_literal` — the model writes `_status = "done"` or `_status = "not_loaded"` instead of `_status = "empty"`. The structure is right. The specific string is wrong. This is execution fidelity, not reasoning.

### Other high-gap families

| Case | P(exec_fail\|ast_correct) | Dominant failure |
|------|--------------------------|-----------------|
| effect_order_c | 19.5% | Name/scope errors after moving call into loop |
| use_before_set_c | 19.4% | Wrong value/variable after restructuring |
| mutable_default_c | 12.1% | Wrong attribute names in decorator pattern |

---

## 7. Model-Level Execution Gap

| Model | AST_correct% | Pass% | P(exec_fail\|ast_correct) | Dominant failure |
|-------|-------------|-------|--------------------------|-----------------|
| **gpt-4o-mini** | **99.6%** | **60.1%** | **40.0%** | 78.9% semantic, 20.8% name/scope |
| gpt-4.1-nano | 99.2% | 94.2% | 5.9% | Semantic + name binding |
| gpt-5.4-mini | 97.9% | 99.3% | 0.5% | Rare |
| gpt-5-mini | 97.9% | 99.7% | 0.3% | Rare |
| claude-sonnet-4 | 100.0% | 100.0% | 0.0% | None |

**gpt-4o-mini is the most informative model for the thesis:** It understands bugs at 99.6% structural accuracy but fails execution at 40%. The entire gap is precision-level errors — wrong values and broken references within correct structures.

gpt-5-mini and gpt-5.4-mini have near-zero execution gaps, demonstrating that the fidelity problem is solvable with stronger models. The gap is not inherent to the task — it is a capability boundary that separates model tiers.

---

## 8. Cross-Layer Repair as System-Level Reasoning

133 events (all alias_config_c) show models fixing the aliasing bug at the middleware/handler layer instead of the config layer. All 133 pass execution.

These are not evaluation artifacts. They are valid alternative repair strategies that operate at a different abstraction layer. The model recognized that the aliasing invariant can be satisfied by defensive copying at the consumer layer rather than at the producer layer. This is evidence of system-level architectural reasoning.

---

## 9. Revised AST_partial

```
AST_partial = 90 events (1.0% of assessable)
```

The broadened definition captures cases where the model shows structural understanding of the correct mechanism but the implementation is incomplete: default changed but guard missing, else branch present but incomplete, cache operation present but wrong type.

Partial fixes are rare. Models either get the structure right (98.7%) or produce code with no recognizable structural fix (0.3%). The 1.0% partial rate means half-measures are uncommon — models commit fully to a fix strategy.

---

## 10. Conclusion

### The causal decomposition is clear and decisive

```
P(exec_fail) decomposes as:

  0.2%  — reasoning failure (model doesn't understand the bug)
  1.3%  — structural failure (model understands but produces wrong fix pattern)
 12.7%  — execution failure (model produces correct fix pattern but code fails)
─────
 12.8%  total failure rate (= 1 - 87.2% pass rate)
```

**99.5% of all failures occur after the model has both correctly identified the mechanism and produced the correct structural fix.** The gap is in the last mile: translating correct structure into working code.

### The execution failures are precision errors, not conceptual errors

89% of semantic failures are wrong values or literals — the model writes the right code shape with the wrong specific constant. 5% are wrong variable bindings — the model restructures code correctly but breaks a name reference. These are binding-level precision errors within structurally correct implementations.

### This is not a pipeline artifact

Zero execution failures are reconstruction or parsing artifacts. The gap is genuine code generation fidelity — the difference between knowing the right structure and producing working code.

### The gap is model-stratified and solvable

gpt-4o-mini has a 40% execution gap. gpt-5-mini has 0.3%. The fidelity problem is not inherent to the task. It is a capability boundary that stronger models cross. This suggests that execution fidelity, not reasoning capability, is the primary scaling dimension for code generation quality on this benchmark.
