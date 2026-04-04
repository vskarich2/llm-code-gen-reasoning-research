# AST Verifier Evolution Plan v5 — Final Tightening

**Date:** 2026-04-03
**Supersedes:** v4 sections where specified
**Scope:** 6 precision fixes to eliminate overclaiming and ambiguity

---

## 1. Interpretation of AST vs Execution Disagreement

AST does not correct execution. Execution measures behavioral correctness (did the code pass the test). AST measures structural pattern presence (does the code contain the fix pattern). These are independent measurements of different properties.

When AST and execution disagree, neither is "right" — they are measuring different things:

- **AST=correct, exec=fail:** The fix pattern is structurally present but the code fails at runtime. This does not mean execution is wrong. It means the structural fix was insufficient for behavioral correctness (e.g., correct shape but wrong value).

- **AST=incorrect, exec=pass:** The code passes the test but does not contain a recognized fix pattern. This does not mean AST is wrong. It means the model used an unrecognized approach (novel alternative or pattern-matched lucky fix).

The oracle is the reference signal for reasoning correctness. When we compare AST and execution against the oracle:

- AST agrees with the oracle on 93.4% of events
- Execution agrees with the oracle on 84.4% of events

This means **AST aligns with the oracle-defined reasoning signal better than execution does** — not that AST is more accurate than execution. Execution measures behavior; AST measures structure; the oracle measures reasoning. They are three axes, not competitors.

### Corrected language

All instances of "AST correctly reclassifies" in prior versions should be read as: "AST provides a structural classification that aligns more closely with oracle-assessed reasoning correctness than execution pass/fail does."

---

## 2. Unknown Rate: Estimate Status

The 2.3% unknown rate (454 events) is an **estimate**, not a measured fact under the proposed policy. It is derived by reclassifying the current LUCKY_FIX bucket (AST=incorrect, exec=pass) as `unknown`, which is an approximation because:

1. The actual `unknown` state requires verifying that no anti-pattern is present AND the target function was modified. The current LUCKY_FIX count does not apply these additional checks.

2. Some current LUCKY_FIX events may have anti-patterns present (which would make them `incorrect`, not `unknown`). This would reduce the unknown count.

3. Some current `incorrect` events with exec=fail may also qualify as `unknown` (no anti-pattern, target modified, but exec fails). This would increase the unknown count.

**The unknown rate must be re-measured after implementing the `unknown` classification rules.** The 2.3% is a reasonable upper-bound estimate for planning purposes. The actual rate may be 1.5–2.5%.

Per-family estimates carry the same caveat. The l3_state_pipeline estimate (34.7%) is the most reliable because its LUCKY_FIX events are well-understood (commit-only partial fixes).

---

## 3. Limits of Failure Decomposition

The execution-failure decomposition presented in this plan is **exploratory and indicative, not definitive ground truth.**

### Specific limitations

1. **52% of AST-correct execution failures are "unclassified invariant violation."** These require manual labeling. Until that manual review is complete, the decomposition is partial. The rule-based categories (import failure, name error, wrong value, unexpected exception) cover only 48% of events.

2. **Manual classification is single-annotator.** The planned protocol uses one reviewer. There is no inter-annotator agreement measurement. Classification reliability is therefore unknown. If the decomposition appears in the paper as a table or figure, a second annotator should review a 50-event subsample and report agreement rate.

3. **Rule-based labels are heuristic.** The regex patterns on failure_reasons text are approximations. "expected X got Y" is labeled as `wrong_value_literal`, but some of these may actually be test-contract mismatches or incomplete path coverage. The rules are a first-pass classification, not ground truth.

4. **The decomposition is computed on a subset.** The 1,046 events from the prior analysis are from specific log runs. The full 2,242 AST-correct execution failures across the 20,031-event dataset have not all been decomposed. Proportions from the sample are extrapolated.

### What this means for the paper

The decomposition should be presented as: "An exploratory analysis of AST-correct execution failures suggests the following approximate distribution..." — not as precise measured rates. The main finding (that execution failures are dominated by semantic precision errors within structurally correct code, not by reconstruction artifacts) is robust to reasonable variation in the category proportions. The specific percentages per subtype should be presented with uncertainty.

---

## 4. Measured vs Expected Labels in AST vs Baseline

### Measured results (from 20,031 oracle-labeled events)

| Signal | Oracle agreement | Status |
|--------|-----------------|--------|
| Execution only | 84.4% | **Measured** |
| Old LLM classifier | 90.5% | **Measured** |
| AST structural | 93.4% | **Measured** |
| AST incremental over execution | +9.0pp | **Measured** |
| AST incremental over classifier | +2.9pp | **Measured** |
| AST uniquely oracle-aligned events (net) | 2,088 | **Measured** |

### Planned experiment (not yet measured)

| Signal | Expected oracle agreement | Status |
|--------|--------------------------|--------|
| Locus probe (function-name match only) | ~88-90% | **Expected — not measured** |
| Locus probe incremental over execution | ~4-6pp | **Expected — not measured** |
| Full AST incremental over locus probe | ~3-5pp | **Expected — not measured** |

The locus probe experiment has not been run. The expected values are estimates based on the observation that locus matching is a subset of what full AST checks. If the locus probe achieves >92% oracle agreement when measured, the incremental value of full pattern matching is smaller than estimated and should be reassessed per family.

---

## 5. AST Agreement Does Not Imply Causal Understanding

AST structural correctness is a necessary but not sufficient condition for genuine bug understanding. The verifier detects that the code contains the right fix pattern. It cannot determine WHY the model produced that pattern. Three possibilities are indistinguishable by AST:

1. **Genuine reasoning:** The model traced the bug mechanism, understood the invariant, and produced the fix because it understood why it was needed.

2. **Pattern recall:** The model recognized the code pattern from training data (e.g., "mutable default → use None + guard" is a well-known Python idiom) and applied the memorized fix without causal understanding.

3. **Statistical correlation:** The model's generation was influenced by distributional regularities in training data that happen to correlate with the correct fix, without any explicit pattern matching or reasoning.

AST cannot distinguish these. The 2.3% of events where the oracle says reasoning is wrong but AST says structure is correct (the `oracle_structure_disagreement_pass` cell) provides a lower bound on pattern-recall frequency, but the true rate may be higher — some pattern-recall events may also have oracle=correct (the oracle evaluates the reasoning trace, which a pattern-recalling model might also generate correctly).

**This limitation is fundamental, not fixable.** No static analysis of code structure can establish the causal process that produced it. The paper must state this clearly and not imply that AST correctness = understanding.

---

## 6. Sharpened Core Claim

The central finding, stated precisely:

> Of 3,837 execution failures across 20,031 oracle-labeled evaluation events, 58.4% (2,242 events) occur in cases where both the oracle reasoning evaluator and AST structural verification indicate correct reasoning and correct structural implementation, yet execution fails. This execution-fidelity gap is the dominant failure mode, exceeding reasoning failure (34.4%) and structural translation failure (7.2%). The gap is model-stratified (ranging from 0% for claude-sonnet-4 to 28.4% for gpt-4o-mini), family-stratified (ranging from 0% to 63.6%), and intervention-responsive (reduced from 14.2% under baseline to 6.7% under reasoning-only critique).

This claim:
- States the measurement instruments explicitly (oracle + AST)
- Does not claim AST measures reasoning (it verifies structural implementation)
- Does not claim AST corrects execution (it provides a different axis)
- Quantifies the finding with exact counts and rates
- Acknowledges the finding is conditional on both oracle and AST validity (which are independently validated at 93.4% mutual agreement)
- Does not attribute causality to the gap (it could be precision errors, test-contract issues, or import failures — the decomposition in Section 3 is exploratory)
