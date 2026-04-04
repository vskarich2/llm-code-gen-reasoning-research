"""Documentation strings for every dashboard tab.

Each tab has an operational documentation string — not just schema,
but how to think with it: what it measures, what it does NOT measure,
how to interpret it, and what to check when numbers look wrong.

Rendered in a collapsible expander at the top of each tab.
"""

from __future__ import annotations

TAB_DOCS: dict[str, str] = {
    "overview": """\
**What this tab is for:** the macro picture. Which models and conditions are strong or weak, and where the big differences are.

**Metric cards (top row):**
- **Pass Rate** = `mean(exec_pass)`. Your ground-truth behavioral success metric. If this is low, something upstream is failing — but you don't yet know where. Go to Failure Decomposition.
- **LEG Rate** = `mean(oracle_correct AND NOT exec_pass)`. The core phenomenon: the model *understood the bug* but failed to implement the fix. High LEG = reasoning signal exists, implementation is the bottleneck. Uses oracle labels when available.
- **Lucky Fix Rate** = `mean(NOT oracle_correct AND exec_pass)`. The opposite: code works but reasoning is wrong. High lucky fix = model is exploiting heuristics, not understanding.
- **Reasoning Rate** = `mean(oracle_correct)`. The oracle's ground-truth judgment. If oracle labels are not available, falls back to classifier-derived reasoning_sufficient.
- **Count** = number of attempts. Many metrics become meaningless at low N.

**Heatmap:** pivot of one selected metric across models (rows) × conditions (columns). Darker = higher. Use the dropdown to switch metrics.

**Detailed Table:** same data in flat form with all metrics and abbreviated column headers.

**Cluster Analysis (bottom):** 3-way decomposition (Oracle/Classifier × AST × Execution) into 8 mutually exclusive categories, causal failure staging, execution gap hotspots by case. Both Oracle and Classifier tabs are shown when both signals are available — no fallback, both always render.
""",

    "failure_taxonomy": """\
## Failure Taxonomy (4-Axis Causal Decomposition)

This tab decomposes every evaluation attempt into three independent axes and their cross-products.

### The Three Axes

| Axis | Symbol | Source | Question |
|------|--------|--------|----------|
| **Reasoning** | R | Oracle evaluator | Did the model correctly identify the bug mechanism? |
| **Translation** | T | Blind classifier | Is the generated code internally consistent with the stated reasoning? |
| **Execution** | E | Test harness | Did the generated code pass all tests? |

### Outcome Classes

The R × E matrix produces four primary outcomes:
- **Interpretable Success** (R=1, E=1): model understood the bug AND produced working code
- **LEG** (R=1, E=0): model understood the bug but code doesn't work — the Latent Execution Gap
- **Lucky Fix** (R=0, E=1): code works but reasoning was wrong — accidental correctness
- **Reasoning Failure** (R=0, E=0): wrong reasoning, wrong code

### LEG Subtypes (the key finding)

LEG cases are further split using the Translation axis:
- **execution_failure** (T=1): reasoning correct, code reflects reasoning, but tests fail anyway — a pure implementation bug
- **translation_failure** (T=0): reasoning correct, but code doesn't reflect the reasoning — the model couldn't translate understanding into code

### R × T Matrix (Diagnostic)

The R × T cross-product reveals classifier-oracle alignment:
- **R=1, T=1**: correct reasoning, consistent code (ideal)
- **R=1, T=0**: correct reasoning, inconsistent code (translation gap)
- **R=0, T=1**: wrong reasoning, but code is internally consistent with it (coherent incorrectness)
- **R=0, T=0**: wrong reasoning AND inconsistent code (incoherent incorrectness)

### Important Notes

- R comes from the **oracle** (ground-truth comparison), NOT the classifier
- T comes from the **classifier** (internal consistency check), NOT the oracle
- These are independent measurements — disagreement between them is informative, not an error
- PARTIAL oracle verdicts are shown separately in the Oracle Granularity section
""",

    "three_axis": """\
**What this tab is for:** the formal decomposition that makes the benchmark scientifically meaningful. Without this, all you have is pass/fail.

**The four axes (v3.1):**
- **S (Serialization):** did the output become executable code? Combines parse success + reconstruction success + execution eligibility.
- **R (Reasoning):** did the oracle judge reasoning as correct? Based on ground-truth comparison of model's stated root cause against the actual bug mechanism. `oracle_correct = True` when oracle verdict is CORRECT or PARTIAL (lenient mode).
- **T (Translation):** is the generated code internally consistent with the stated reasoning? From the blind classifier: `T = RIC AND CCC` where RIC = reasoning_internal_consistency and CCC = commitments_code_consistency.
- **E (Execution):** did tests pass? The hard behavioral outcome.

**Outcome classes (R × E primary, T for subtyping):**

| Class | R | E | What it means |
|-------|---|---|---------------|
| Interpretable Success | 1 | 1 | Model understood AND implemented correctly. |
| **LEG** | **1** | **0** | **Model understood the bug but code doesn't work.** |
| Lucky Fix | 0 | 1 | Code works but reasoning is wrong. Accidental correctness. |
| Coherent Incorrect | 0 | 0 (T=1) | Wrong reasoning, but code is internally consistent with it. |
| Incoherent Incorrect | 0 | 0 (T=0) | Wrong reasoning AND code doesn't match it. |

**LEG Subtypes (the key finding):**
- **execution_failure** (T=1): reasoning correct, code reflects reasoning, but tests fail anyway — a pure implementation bug
- **translation_failure** (T=0): reasoning correct, but code doesn't reflect the reasoning — the model couldn't translate understanding into code

**V3 Classifier dimensions (internal consistency, NOT correctness):**
- **RIC** (reasoning_internal_consistency): does root cause logically support fix strategy?
- **CIC** (commitments_internal_consistency): do commitments follow from fix strategy?
- **CCC** (commitments_code_consistency): does code implement the commitments?
- **RCA** (reasoning_code_alignment): does code match the stated fix strategy?

Each dimension also has a justification — one sentence explaining the judgment, visible in Pipeline Trace.

**When numbers look wrong:** if serialization_failure is high, your LEG/pass rates are computed on a biased subset. Always check serialization rate first. If oracle coverage is low (many UNJUDGABLE), the R axis is measured on a subset.
""",

    "failure": """\
**What this tab is for:** locating bottlenecks. Not ranking models — diagnosing *where* in the actual pipeline code an attempt breaks.

---

### The four metric cards — what they measure and where in the pipeline each one is determined

---

#### Parse Failure

**What happens in the pipeline:** the generation model returns raw text. `core/pipeline/parsing/parser_v2.py` tries to extract valid JSON from it. `parse_v2_execution()` runs strict parsing; `parse_v2_recovery()` runs a more lenient parse. Then `execution_v2.py:_select_artifact()` decides which parse to use (strict preferred, recovery fallback). If BOTH fail, `routing.selected_source = "none"` and the attempt is dead.

**What determines `parse_status`:** in `parser_v2.py:_validate_and_build()`, the parsed JSON is checked against the generation schema — does it have `root_cause`, `fix_strategy`, `files`? If schema-valid → `"success"`. If partially valid → `"partial"`. If JSON couldn't be extracted at all → `"failed"`.

**Why it fails:** model returned prose instead of JSON. Model returned a diff. Truncated output. Malformed JSON syntax. Model ignored the output format instructions entirely.

**If this is high:** the prompt isn't working — the model doesn't understand the required output format.

---

#### Reconstruction Failure

**What happens in the pipeline:** after parsing extracts `files_dict` from the JSON, `core/pipeline/reconstructor.py:reconstruct_strict()` validates every file through a 5-gate pipeline:

1. **Gate 1 — UNCHANGED check:** if value is literally `"UNCHANGED"`, accept the original file content
2. **Gate 2 — Empty check:** if value is empty/whitespace → `RECON_EMPTY_FILE` (hard fail)
3. **Gate 3 — Sentinel detection:** `_is_no_change_phrase()` checks if value is a paraphrase like "no changes needed", "same as original" → `RECON_SENTINEL_MISMATCH` (hard fail)
4. **Gate 4 — AST validation:** `ast.parse(normalized_content)` — is it valid Python? If syntax error, attempt recovery (fence stripping, prefix stripping, leading-whitespace dedent). If still fails → `RECON_INVALID_CODE`
5. **Gate 5 — Semantic check:** `_check_semantic_structure()` compares top-level defs against original (diagnostic only, never blocks)

Before the gates, if the model omitted files entirely, auto-fill kicks in — missing keys get filled with `"UNCHANGED"` and tracked as `missing_files_auto_filled` recovery.

**Possible statuses:** `SUCCESS`, `RECON_MISSING_FILES`, `RECON_EMPTY_FILE`, `RECON_SENTINEL_MISMATCH`, `RECON_INVALID_CODE`. Also `GENERATION_CONTRACT_VIOLATION` if the parsed JSON lacks required fields (set in `execution_v2.py`).

**Why it fails:** model wrapped code in markdown fences (recovered by fence stripping). Model added "FULLY UPDATED" prefix (recovered by prefix stripping). Model added leading space to file values (recovered by dedent). Model produced actual syntax errors in the Python. Model omitted files. Model wrote "no changes" instead of actual code.

**If this is high:** check `recon_status` values to see which gate is failing. Check `recovery_types` to see what's being recovered vs what's genuinely broken.

---

#### Execution Failure

**What happens in the pipeline:** `core/pipeline/execution/exec_canonical.py:exec_canonical()` writes the reconstructed files to a temp directory and launches `core/harness/run_case.py` as a subprocess. The subprocess:

1. Imports all Python files in the package directory
2. Merges their namespaces into a single module
3. Locates the test function (`test_{difficulty}` or `test`)
4. Runs `test_fn(merged_namespace)` — the test returns `(passed: bool, reasons: list)`
5. Reports back: status, passed, error_type, failure_reasons, execution_trace, functions_detected, functions_called

Back in `exec_canonical.py:_classify()`, the subprocess output is categorized: `EXECUTION_SUCCESS` (passed=True), `INVARIANT_FAILURE` (test returned False), `INVARIANT_CRASH` (test raised an exception), `NAME_ERROR`, `IMPORT_FAILURE`, `SYNTAX_FAILURE`, `TIMEOUT`, etc.

**What `exec_pass` means:** the test function returned `passed=True`. The model's code was imported, merged, executed, and the test assertion passed.

**Why it fails:** the model's code runs but doesn't actually fix the bug. Wrong logic, wrong variable, partial fix, or correct reasoning that didn't translate into correct code. **This is the scientifically interesting failure mode** — the model got past all formatting hurdles and produced real code that just doesn't work.

**If this is high:** the bottleneck is code quality, not formatting. Go to Pipeline Trace to see what the code does wrong. Compare with mechanism_dim to check if the model at least understood the bug (LEG) or missed it entirely (reasoning failure).

---

#### Reasoning Failure

**Two independent reasoning signals exist:**

**1. Oracle (ground truth):** `core/evaluation/oracle_eval/reasoning_truth.py` sends the model's raw root_cause and fix_strategy to an oracle LLM that compares against the case's ground-truth bug specification. Returns CORRECT / PARTIAL / WRONG / UNJUDGABLE. This is the authoritative signal — `oracle_correct` derives from it.

**2. Blind classifier (internal consistency):** `core/evaluation/evaluator_v2.py:classify_case()` sends the model's reasoning + generated code to an evaluator LLM that checks internal consistency (NOT correctness). Returns 4 dimensions:
- **RIC** (reasoning_internal_consistency): does root cause support fix strategy?
- **CIC** (commitments_internal_consistency): do commitments follow from strategy?
- **CCC** (commitments_code_consistency): does code implement commitments?
- **RCA** (reasoning_code_alignment): does code match stated strategy?

Each dimension includes a one-sentence justification (debug only, visible in Pipeline Trace).

**What determines reasoning failure:** `oracle_correct == False`. If the oracle says the model didn't identify the correct mechanism, reasoning is wrong. The blind classifier measures translation fidelity, NOT reasoning correctness.

**If this is high:** models genuinely can't reason about these bugs. Compare oracle vs classifier agreement — if classifier says CORRECT but oracle says WRONG, the model produced plausible-sounding but incorrect reasoning.

---

### Terminal Stage vs metric cards

The four metric cards show **raw boolean means** — they can overlap (an attempt can have both reconstruction_failure and execution_failure). The **Terminal Stage chart** assigns each attempt to exactly ONE stage — the first stage where it fails. This gives a mutually exclusive decomposition. Reasoning failure is NOT in terminal stage because it's evaluated independently.

### Failure Funnel

Shows cumulative attrition: all_attempts → execution_eligible → reconstruction_ok → execution_pass → reasoning_correct. Each drop = loss at that pipeline stage.

### When to use this tab

- **First stop when pass rate is low.** Understand whether the bottleneck is formatting (parse/recon) or logic (execution) before investigating individual cases.
- **After changing prompts.** Did the new prompt shift failures between stages?
- **Before drawing conclusions about model capability.** If 30% of attempts die at reconstruction, your execution pass rate is computed on a biased subset.
""",

    "case_explorer": """\
**What this tab is for:** following one retry chain through time. Use this when you want to understand *temporal dynamics*, not just final outcomes.

**What to look for:**
- Does retry improve execution? (attempt 0 fails, later passes)
- Does oracle reasoning improve or degrade across attempts?
- Does translation consistency (classifier T axis) improve with retry?
- Do they diverge? (oracle improves but code regresses — common and important)
- Does the model get lucky on a later attempt? (oracle gets worse but code passes)

**Per-attempt signals (v3.1):**
- **Oracle verdict:** CORRECT / PARTIAL / WRONG / UNJUDGABLE — did reasoning improve?
- **Classifier dims (RIC, CIC, CCC, RCA):** did internal consistency improve?
- **AST status:** did structural correctness improve?
- **Execution:** did the code pass tests?

**Outcome labels:** `interpretable_success`, `LEG` (oracle OK, code fails), `lucky_fix` (code works, oracle wrong), `coherent_incorrect` (wrong reasoning, consistent code), `incoherent_incorrect` (wrong reasoning, inconsistent code).

**Key insight:** don't only look at the last attempt. Track oracle verdicts AND classifier dims across the chain. A common pattern: oracle stays CORRECT throughout but T flips between attempts — the model's translation quality is volatile.
""",

    "pipeline_trace": """\
**What this tab is for:** this is your debugger. When something looks wrong anywhere else in the dashboard, come here.

**Left column (input → validation):**
- **Prompt:** what the model actually saw. File keys are bare filenames (e.g., `config.py`, not full storage paths).
- **Parse:** structural validity flags — strict_parse_valid, recovery_parse_valid, execution_eligible.
- **Reconstruction:** files_changed/missing/extra, syntax_errors, recovery_types.

**Right column (output → evaluation):**
- **Raw Response:** what the model produced.
- **Execution:** exec_pass, exec_category, exec_reasons, execution_trace, functions_detected vs functions_called.
- **Oracle:** ground-truth reasoning verdict (CORRECT/PARTIAL/WRONG/UNJUDGABLE). Independent of classifier and execution.
- **Classifier (v3):** 4 internal-consistency dimensions (RIC, CIC, CCC, RCA), each with a one-sentence justification. Measures whether reasoning ↔ code is self-consistent, NOT whether reasoning is correct.
- **Metrics:** outcome_class, LEG, LEG_subtype.

**How to use:** when a row is marked LEG, check the oracle verdict (must be CORRECT/PARTIAL) and the classifier justifications. The oracle tells you the model understood the bug. The classifier justifications tell you WHERE the translation broke down. Read the extracted code to see the actual implementation gap.

**Key distinction:** Oracle = "did the model identify the real bug?" Classifier = "is the code consistent with the model's stated reasoning?" These are independent. Disagreement between them is informative.
""",

    "ast_analysis": """\
### What this tab measures

This page is **not about whether the model passed tests.** It is about **what kind of code the model actually produced**, independent of execution.

If the Execution tab tells you *"did it work?"*, this tab tells you: **"What did the model actually build?"**

Most evaluation collapses everything into pass/fail. That hides critical distinctions: did the model fail because it didn't understand the problem? Because it understood but implemented incorrectly? Because it never produced valid code at all? Tests cannot reliably answer these questions.

**AST analysis isolates structural correctness from behavioral correctness.** It answers: did the model produce the right functions, with the right interfaces, in the right places? — before we even ask whether the code works.

---

### AST Status definitions (strict)

| Status | Meaning | Example |
|--------|---------|---------|
| **correct** | All required structural elements present and correctly defined. Functions exist, names match, arguments match expected signature. **Says nothing about logic correctness** — you can have perfect structure with completely wrong behavior. | `alias_config_a`: model writes `create_config()` that calls `DEFAULTS.copy()` — correct structure. Whether the copy is deep enough is a behavioral question. |
| **incorrect** | Structure exists but is wrong or incomplete. Missing required function, wrong name, wrong number of arguments, incorrect nesting. | `alias_config_a`: model writes `create_config()` but does `return DEFAULTS` (direct reference, no copy). The AST anti-checker catches this — returning the raw dict without copying is the exact bug pattern. |
| **unknown** | Structure partially matches but cannot be confidently classified. Function exists but signature is ambiguous, or dynamic behavior obscures structure. Treat cautiously. | A function that constructs a dict dynamically in a way that neither matches the copy pattern (correct) nor the direct-return pattern (anti). |
| **not_available** | No valid AST could be constructed. Serialization failed, code is syntactically invalid, files missing, reconstruction failed. **Not a reasoning failure** — it is a serialization/system failure. | Model output couldn't be parsed into valid Python at all, or the reconstructor couldn't produce the target file. |
| **not_measurable** | No AST verification rules exist for this case. Behavior-only tasks, pure transformation tasks, or cases where structural correctness isn't meaningful to check. | Complex multi-file cases like `l3_state_pipeline` where the fix is behavioral (restoring a function call), not structural (adding/changing function definitions). |

---

### How AST checking works (concrete examples)

Each case has checker rules that look for specific AST patterns in the model's generated code:

**Example 1 — `alias_config` family (copy-on-return)**
- **Bug:** `create_config()` returns `DEFAULTS` directly, so mutations leak across calls
- **Correct fix structure:** calls `DEFAULTS.copy()`, `dict(DEFAULTS)`, or `{**DEFAULTS}`
- **AST strict check:** looks for `DEFAULTS.copy()` call inside `create_config()`
- **AST relaxed check:** also accepts `dict(DEFAULTS)`, `{**DEFAULTS}`, or `deepcopy(DEFAULTS)`
- **AST anti-check:** catches `return DEFAULTS` (direct reference) or `x = DEFAULTS` (alias assignment) — these are the exact bug patterns
- **Correct = relaxed passes AND anti-check does NOT fire**

**Example 2 — `stale_cache` family (cache invalidation)**
- **Bug:** `update_product()` writes to DB but doesn't invalidate the cache
- **Correct fix structure:** calls `invalidate()`, `pop()`, `clear()`, `delete()`, or similar on the cache inside `update_product()`
- **AST check:** looks for any call to a known invalidation function within the target function
- **Incorrect:** model rewrites `update_product()` without any cache invalidation call

**Example 3 — `effect_order` family (side-effect inside loop)**
- **Bug:** side-effect call (snapshot/emit/audit) is outside the processing loop, fires only once
- **Correct fix structure:** the side-effect call must be inside a `for` loop body
- **AST check:** walks the function, finds `For` nodes, checks if a known side-effect call is inside the loop body
- **Incorrect:** model puts the side-effect call after the loop, or in a separate function

---

### Relationship to the four-axis evaluation system

| Axis | Symbol | Source | Question |
|------|--------|--------|----------|
| Serialization | S | Parser + reconstructor | Can code be constructed from model output? |
| Reasoning | R | Oracle | Did the model correctly identify the bug mechanism? |
| Translation | T | Blind classifier | Is the code internally consistent with the stated reasoning? |
| Execution | E | Test harness | Did the code pass tests? |

**AST is NOT one of these axes.** It is a deterministic structural signal between translation and execution:

```
Reasoning → Translation → [AST structure] → Execution
```

---

### The critical insight: AST + LEG + LEG subtypes

**High AST correctness in LEG events = the strongest form of LEG.**

If you observe: Oracle = CORRECT, AST = correct, Execution = fail — then the model understood the bug, built the correct structure, but failed at semantic implementation. This is **execution-semantic failure**.

**LEG subtypes refine this further:**
- **execution_failure** (T=1, AST=correct): reasoning correct, code reflects reasoning, structure correct, but tests fail. Pure implementation bug — the hardest and most interesting failure.
- **translation_failure** (T=0, AST=varies): reasoning correct, but code doesn't match the stated fix strategy. The model couldn't translate understanding into code.

**AST × Classifier Dimensions** (new section below): shows how structural correctness relates to each v3 classifier dimension. High AST + low CCC (commitments_code_consistency) = model built the right structure but the classifier thinks commitments weren't fully implemented.

**AST × Oracle** (new section below): crosstab of oracle reasoning correctness vs AST structural correctness.

---

### Expected patterns by outcome class

| Outcome Class | Expected AST | Interpretation |
|---------------|-------------|----------------|
| **Interpretable Success** | Very high correctness | Structure correct, logic correct |
| **Serialization Failure** | not_available | Model never produced valid code |
| **LEG (execution_failure)** | correct | **Strongest LEG** — reasoning + structure + translation all correct, tests still fail |
| **LEG (translation_failure)** | varies | Reasoning correct but translation broke — structure may or may not be right |
| **Lucky Fix** | Often correct | Code works but reasoning is wrong — accidental correctness |
| **Coherent Incorrect** | Often correct | Wrong reasoning, but code matches it — internally consistent failure |
| **Incoherent Incorrect** | Often low | Wrong reasoning AND code doesn't match — disorganized failure |

---

### How to use this page

1. **Distribution first:** is AST mostly correct, or are structural failures common?
2. **Cross with outcome class:** high AST + high LEG = semantic failure. Low AST + high reasoning failure = structural failure.
3. **Compare across interventions:** does retry improve AST, or just execution? If retry improves execution without improving AST, the model is finding behavioral workarounds, not structural fixes.
4. **Inspect examples:** use the filters below to see concrete cases of each pattern.
""",

    "family_breakdown": None,  # loaded from family_docs.py at module init

    "model_condition": """\
**What this tab is for:** the ablation core view. This is where you answer "does this prompt help?" and "which model is better?"

**How to read it:**
- Compare **conditions within a model** to measure prompt effectiveness. If `leg_reduction_v3` has higher Pass% than `baseline_v3` for the same model, the prompt helped.
- Compare **models within a condition** to measure model capability.
- The gap between **Pass%** and **R%** is the execution fidelity gap — how much reasoning signal is lost in implementation.
- If a prompt helps one model but not another, the effect is model-dependent. Don't generalize.

**Column legend:** Pass% = pass rate, LEG% = LEG rate, Lucky% = lucky fix rate, R% = reasoning rate, N = count.
""",

    "retry_analysis": """\
**What this tab is for:** answering the key question — does retry help or hurt?

**How to interpret:**

| Pattern | Meaning |
|---------|---------|
| High Recov% + Low Degr% | Retry is clearly helpful |
| High Recov% + High Degr% | Retry is volatile — helps some chains, hurts others |
| Low Recov% + Low Degr% | Retry is inert — not doing much |
| Low Recov% + High Degr% | **Retry is actively harmful** — model "unlearns" correct fixes |

- **Recov%** = of chains where attempt 0 failed, what fraction eventually passed
- **Impr%** = fail→pass transitions in multi-attempt chains
- **Degr%** = pass→fail transitions (the harmful case)
- **AvgAtt** = average attempts per chain. High = potentially unstable

**Caution:** these are chain-level metrics. A chain = all attempts for one (model, condition, case, trial). They don't tell you *which* attempt was best — use Case Explorer for that.
""",

    "by_difficulty": """\
**What this tab is for:** checking whether the benchmark's difficulty levels are meaningful and how models scale with difficulty.

**Expected patterns:**
- Pass% should decrease with difficulty. If it doesn't, difficulty labels may be miscalibrated.
- LEG% may increase with difficulty — models understand harder bugs but can't implement fixes. This is the core finding.
- If R% drops with difficulty, models can't even reason about harder bugs (a weaker result).
- Lucky% should decrease — harder cases are harder to accidentally pass.

**Column legend:** Pass% = pass rate, LEG% = LEG rate, Lucky% = lucky fix rate, R% = reasoning rate, N = count.
""",

    "oracle": """\
## Oracle Reasoning Evaluator

### What is this?

The oracle is the **ground-truth reasoning evaluator**. It is an LLM (gpt-5-mini) that compares the model's stated root cause and fix strategy against the **authoritative bug mechanism** from the case metadata. It answers one question: **did the model correctly identify WHY the bug occurs?**

This is the most important measurement in the system. Without it, you cannot distinguish a model that reasons correctly from one that guesses correctly.

### Why does the oracle exist?

The benchmark measures three independent axes:
1. **Execution** (tests) — did the code pass? This is behavioral correctness.
2. **Structure** (AST) — does the code contain the right structural pattern? This is static analysis.
3. **Reasoning** (oracle) — did the model identify the correct bug mechanism? This is causal understanding.

The central finding of this project is the **Latent Execution Gap (LEG)**: cases where reasoning is correct but execution fails. Without the oracle, LEG is invisible — you'd only see "tests failed" and assume the model didn't understand the bug. The oracle proves it DID understand but couldn't translate that understanding into working code.

### How does the oracle work?

The oracle receives ONLY:
- The model's **raw root_cause** and **raw fix_strategy** (exactly as the model wrote them, before any normalization)
- The case's **ground-truth bug specification** (bug type, location, invariant, fix pattern, mechanism description, known traps)
- The **original buggy code** (what the model analyzed)

The oracle does NOT see:
- The model's generated code (no leakage from execution)
- The classifier's judgment (independent evaluation)
- Test results (independent of behavioral correctness)
- AST checker results (independent of structural analysis)

This isolation is critical. The oracle evaluates reasoning ONLY. It cannot be biased by whether the code happened to pass tests.

### Oracle verdicts

- **CORRECT** — the model correctly identifies the true causal mechanism. It names the right root cause, references the correct location, and captures the causal chain (WHY the bug causes failures, not just WHAT the failure is). Paraphrases are acceptable.
- **PARTIAL** — the model is partially correct. It identifies the correct bug class but gets the causal chain wrong, OR identifies the correct location but wrong mechanism, OR correctly describes part of a multi-step mechanism but misses critical steps, OR falls into a known trap (identifying a real but non-root cause).
- **WRONG** — the model identifies a different mechanism than the oracle, describes only the symptom without identifying why, references the wrong location, or proposes a mechanism contradicted by the code.
- **UNJUDGABLE** — reasoning is missing, empty, or too vague to evaluate.

### PARTIAL handling

PARTIAL is a distinct epistemic category — it represents incomplete causal understanding, not "almost correct." Whether PARTIAL counts as "correct enough" depends on the research question:
- **Lenient mode** (default): CORRECT + PARTIAL = oracle_correct. Used for LEG detection — the model understood enough of the mechanism.
- **Strict mode**: only CORRECT = oracle_correct. Used when you need full causal chain identification.

The mode is logged per-event (`oracle.partial_mode`). Both the raw verdict and the derived boolean are always stored, so you can re-analyze under either mode.

### How the oracle compares to the blind classifier

| Property | Oracle | Blind Classifier |
|----------|--------|-----------------|
| Input: reasoning | Raw (pre-normalization) | Normalized |
| Input: code | Never sees generated code | Sees reconstructed code |
| Input: ground truth | Yes (case bug spec) | No |
| What it judges | Reasoning vs true mechanism | Reasoning vs generated code coherence |
| Known bias | ~3-5% undercall (paraphrase miss) | ~11% overcall (says CORRECT when oracle says WRONG) |
| Independence | Independent of execution + classifier | Independent of execution + oracle |

The classifier has a known overcalling problem: it says "mechanism correct" ~99% of the time (v2) or ~97% (v3), while the oracle says ~88%. The **disagreement rate** between them reveals where the classifier is wrong — typically on harder cases where the model uses plausible-sounding but incorrect reasoning.

### How the oracle compares to execution (tests)

Execution tests whether the code WORKS. The oracle tests whether the model UNDERSTANDS. These are independent:

| Oracle | Execution | Interpretation |
|--------|-----------|---------------|
| CORRECT | PASS | **Interpretable success** — model understood and implemented correctly |
| CORRECT | FAIL | **LEG** — model understood but implementation failed. The core finding. |
| WRONG | PASS | **Lucky fix** — model got the code right by accident or pattern matching |
| WRONG | FAIL | **Reasoning failure** — model didn't understand and code is wrong |

### How the oracle compares to AST (structural analysis)

AST checks whether the generated code contains the correct structural pattern (e.g., the right function calls, the right control flow). It's a deterministic, non-LLM signal:

| Oracle | AST | Interpretation |
|--------|-----|---------------|
| CORRECT | correct | **LEG_combined** — strongest LEG signal. Reasoning correct AND structure correct, but tests still fail. |
| CORRECT | incorrect | Reasoning correct but wrong code structure — model understands the bug but generates the wrong fix pattern |
| WRONG | correct | Rare — correct structure without correct reasoning suggests pattern matching |
| WRONG | incorrect | Both wrong — model neither understands nor produces correct structure |

### Disagreement analysis

The **classifier-oracle disagreement** section shows where the blind classifier and the ground-truth oracle diverge:
- **Agreement** — both say correct or both say incorrect
- **Classifier overcall** — classifier says CORRECT, oracle says WRONG. The classifier is fooled by plausible reasoning.
- **Classifier undercall** — classifier says WRONG, oracle says CORRECT. The classifier is too strict (usually a parsing issue).

High overcall rates on specific case families indicate the classifier's prompt needs calibration for those bug types.

### Oracle error model

The oracle is a **measurement instrument**, not absolute truth. Its accuracy depends on:
- Quality of case ground-truth metadata (~2-3% estimated error from incomplete specs)
- LLM evaluator fidelity (~3-5% paraphrase miss rate)
- Rubric boundary noise (~5-8% on PARTIAL vs WRONG boundary)
- LLM non-determinism (<1% at temperature=0)

Always report oracle version, model, coverage rate, and partial_mode in analysis. Never claim oracle = truth.

### Per-attempt alignment (v3.1)

In the v3.1 schema, the oracle runs on EVERY attempt in a retry chain — not just the final one. This enables:
- Tracking whether reasoning improves across retries
- Per-attempt LEG detection
- Disagreement evolution curves
- Causal analysis of critique feedback effects on reasoning

Every trajectory entry contains aligned signals from all four axes: execution, oracle, classifier, and AST.
""",

    "field_introspection": """\
**What this tab is for:** schema debugging. When dashboard numbers look suspicious, check here first.

**What to look for:**
- **High null%** (red highlighting) — field not logged for some events, or conditional (e.g., oracle_verdict only exists for labeled rows). If a metric depends on a high-null field, your effective N is lower than you think.
- **Constants (unique=1, gray italic)** — field doesn't vary. May be a config artifact (e.g., all rows from one model). Not necessarily a bug, but worth understanding.
- **Duplicate-seeming columns** like `reconstruction_status` vs `recon_status` — schema evolution. The dashboard checks both. Understand which one your data actually populates.

**Source column:** trace where each field originates. `payload.*` = from the event payload. `extra.*` = from the extra section. `derived` = computed by the dashboard layer. When in doubt about a derived field, check the underlying source fields.
""",
}

# Load family docs from separate file (too large for inline string)
from dashboard.family_docs import FAMILY_DOCS
TAB_DOCS["family_breakdown"] = FAMILY_DOCS


# ── Column abbreviation mapping ──────────────────────────────

COLUMN_LABELS: dict[str, tuple[str, str]] = {
    # (short_label, description)
    "pass_rate": ("Pass%", "Fraction of attempts where code passes all tests"),
    "leg_rate": ("LEG%", "Latent Execution Gap: correct reasoning, failing code"),
    "lucky_fix_rate": ("Lucky%", "Wrong reasoning but passing code"),
    "reasoning_rate": ("R%", "Fraction with correct reasoning (per classifier)"),
    "count": ("N", "Number of attempts"),
    "retry_recovery_rate": ("Recov%", "Of failed-first chains, fraction that eventually pass"),
    "avg_attempts": ("AvgAtt", "Average attempts per chain"),
    "pct_improved": ("Impr%", "Retry chains that improved (fail to pass)"),
    "pct_degraded": ("Degr%", "Retry chains that degraded (pass to fail)"),
    "mean_score": ("Score", "Average execution score"),
    "recon_pass_rate": ("Recon%", "Pass rate given successful reconstruction"),
}


def abbreviate_columns(
    df: "pd.DataFrame",
    metric_columns: list[str],
) -> tuple["pd.DataFrame", str, list[str]]:
    """Rename metric columns to short labels and return legend text."""
    import pandas as pd

    rename_map: dict[str, str] = {}
    legend_parts: list[str] = []
    for col in metric_columns:
        if col in COLUMN_LABELS:
            short, desc = COLUMN_LABELS[col]
            rename_map[col] = short
            legend_parts.append(f"**{short}** = {desc}")

    renamed = df.rename(columns=rename_map)
    legend = " | ".join(legend_parts) if legend_parts else ""
    short_names = [rename_map.get(c, c) for c in metric_columns]
    return renamed, legend, short_names


def render_tab_docs(tab_key: str) -> None:
    """Render documentation expander for a tab."""
    import streamlit as st

    doc = TAB_DOCS.get(tab_key, "")
    if doc:
        with st.expander("Documentation", expanded=False):
            st.markdown(doc)
