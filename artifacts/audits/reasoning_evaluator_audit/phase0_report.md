# Phase 0 Report: Measurement Audit Results

**Date:** 2026-03-26
**Evaluator model:** gpt-5.4-mini (temperature=0)
**Plan:** fix_reasoning_evaluator_v6.md

---

## Verdict Summary

| Experiment | Result | Verdict | Per plan |
|-----------|--------|---------|----------|
| **P0-2** (terse-correct control) | 4/5 YES, 1 NO | **CONTROL FAILED** | Section 8.4: disqualify classifier |
| **P0-3** (verbose-wrong control) | 5/5 NO | PASS | — |
| **P0-STAB** (stability, temp=0) | 2/10 unstable | **FAILED** | Section 8.5: mandatory voting |
| **P0-6** (parse census) | LR 19.0% parse error, BL 0% | **H3 CONFIRMED** | Parse recovery needed |
| **P0-1** (brevity bias) | 4/15 flips | INCONCLUSIVE | — |

---

## Critical Finding: Classifier Is Unreliable

The classifier is broken in three independent ways:

1. **Brevity bias (P0-2):** Rejects factually correct terse reasoning (`mutable_default_a: "enqueue uses a mutable default argument (queue=[]), so the same list accumulates across calls"` → NO).

2. **Baseline unreliability (P0-1):** Only 5/15 FULL baseline reasoning excerpts rated YES. The classifier rejects 67% of known-good verbose reasoning. This is not a brevity problem — it's a fundamental accuracy problem.

3. **Non-determinism (P0-STAB):** 2/10 cases produced different verdicts across 3 identical calls at temperature=0. The classifier is stochastic.

---

## Decision: Classifier Disqualified (Section 8.8)

Per Section 8.8: "Hard trigger: ANY control fails after fixes. No tuning."

P0-2 control failed. Classifier is disqualified. The three contingency options:

1. **Hybrid** — LLM + rule-based
2. **Rule-based only** — keyword/pattern matching
3. **Abandon automated reasoning** — report code_correct only

**Recommendation: Option 3 — Abandon automated reasoning classification.**

Rationale:
- The classifier cannot reliably evaluate BASELINE reasoning (33% accuracy on full verbose reasoning)
- Even with prompt fixes, non-determinism at temp=0 means results are not reproducible
- Building a hybrid or rule-based system requires ground-truth annotations we don't have
- code_correct is the only metric computed from actual execution (ground truth)
- LEG, lucky fix, and reasoning_correct all depend on the broken classifier

---

## Parse Failure Findings (P0-6)

| Condition | Parse Error Rate | Empty Reasoning |
|-----------|-----------------|-----------------|
| baseline | 0.0% | 0.0% |
| leg_reduction | **19.0%** | **8.6%** |

Fix D (parse recovery gate) is still needed. When parsing fails, reasoning_correct should be None (unknown), not False.

---

## Implication for Metrics

If we drop reasoning_correct, the remaining trustworthy metrics are:

| Metric | Source | Trustworthy? |
|--------|--------|-------------|
| **pass** | exec_evaluate (code execution) | YES |
| **code_correct** | exec_evaluate | YES |
| **score** | exec_evaluate | YES |
| ~~reasoning_correct~~ | LLM classifier | NO — dropped |
| ~~LEG rate~~ | Derived from reasoning_correct | NO — dropped |
| ~~lucky fix rate~~ | Derived from reasoning_correct | NO — dropped |
| **failure_type** | LLM classifier | PARTIAL — still useful for categorization but accuracy unknown |

The research question shifts from "Does the intervention reduce LEG?" to "Does the intervention improve code correctness?"
