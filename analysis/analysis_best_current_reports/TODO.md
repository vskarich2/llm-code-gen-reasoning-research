Good—you’re at the stage where execution matters more than ideas. Here’s the **clean, non-overlapping to-do list**. If you do these well, you have a real shot.

---

# 🚀 CORE PAPER (must-have)

## 1. Lock the Evaluation Protocol

**What:** Finalize definitions + metrics
**Why:** Everything depends on this being unambiguous

* Canonical LEG (3-axis, strict)
* Oracle / Classifier / Execution definitions
* 4 outcome categories (LEG, coherent failure, lucky fix, success)
* Explicit rules (no ambiguity)

👉 Output: **1 clean “Evaluation” section**

---

## 2. Formalize the Reasoning Schema

**What:** Make reasoning verifiable, not textual
**Why:** This is your main novelty

* Mechanism types (10–15 max)
* Slot structure (variables, dependencies, etc.)
* Validation rules (what counts as correct)

👉 Output: **Schema + 5–10 worked examples**

---

## 3. Strengthen the “Oracle” Story

**What:** Clarify what is programmatic vs heuristic
**Why:** Reviewers will attack this

* DDC = invariant-based (strong)
* Shallow = schema-based (explicit rules)
* Be honest: not full formal verification

👉 Output: **Short subsection: “Reasoning Verification”**

---

## 4. Core Results Tables (CRITICAL)

**What:** Add the tables that make your paper “real”
**Why:** This is what convinces reviewers

### MUST include:

**A. 3-axis breakdown**

```
Model | Reasoning | Alignment | Execution | LEG
```

**B. Oracle × Classifier × Execution**

```
Oracle | Classifier | Execution | %
```

**C. Conditional success**

```
P(exec | reasoning correct)
```

👉 Output: **3–4 clean tables**

---

## 5. Statistical Significance

**What:** Show results aren’t noise
**Why:** Required for credibility

* Fisher exact test (for proportions)
* Bootstrap CI (for rates)
* Report p-values + confidence intervals

👉 Output: **1 paragraph + appendix table**

---

# 🔬 EXPERIMENTS (high leverage)

## 6. CoT vs Structured vs None

**What:** Compare reasoning formats
**Why:** Connects to literature + strengthens claim

* No reasoning
* Chain-of-thought
* Your structured schema

Measure:

* reasoning accuracy
* execution accuracy
* mismatch (LEG)

👉 Output: **1 table + 1 paragraph**

---

## 7. SWE-bench Integration (lightweight)

**What:** Show external validity
**Why:** Prevents “toy benchmark” criticism

* Use subset (you already did)
* Map to your framework
* Report LEG + coherent failure

👉 Output: **1 section (don’t overdo it)**

---

# 🧱 BENCHMARK RELEASE (non-negotiable)

## 8. GitHub Repo

**What:** Public, runnable benchmark
**Why:** Reproducibility = credibility

Structure:

```
/benchmark
  cases.json
  run_eval.py
  evaluator.py
  README.md
```

👉 Must run in one command

---

## 9. Evaluation Script

**What:** One command to reproduce results
**Why:** This is what reviewers trust

```
python run_eval.py --model X
```

Outputs:

* per-case metrics
* aggregate tables

---

## 10. Dataset Specification

**What:** Clean, structured cases
**Why:** Makes it a “benchmark,” not examples

Each case includes:

* bug
* ground truth mechanism
* schema fields
* expected fix

---

## 11. (Optional but strong) Website

**What:** Visualization + browsing
**Why:** Helps credibility, not required

Only useful if it shows:

* cases
* oracle decisions
* failure modes

---

# 🧠 FRAMING (this determines acceptance)

## 12. Fix Your Core Claim

**What:** Rewrite how you describe your work
**Why:** This is where papers win/lose

### Your claim should be:

> “We show that reasoning, alignment, and execution are separable—and current evaluations collapse them.”

NOT:

* “we built a benchmark”
* “we analyze bugs”

---

## 13. Position Against CoT

**What:** Address chain-of-thought directly
**Why:** Reviewers expect it

Say:

* CoT = narrative reasoning
* Your method = verifiable reasoning
* They diverge (show with your data)

---

## 14. Anchor to Literature

**What:** Map your terms to known concepts
**Why:** Avoid “this feels ad hoc”

* LEG → reasoning–execution gap
* coherent failure → plausible but wrong reasoning
* lucky fix → spurious success

---

# 📊 CLEANUP (don’t skip)

## 15. Remove Confusions

* Kill old LEG definition
* Clarify classifier role (alignment, not truth)
* Explicitly explain oracle-classifier disagreement

---

## 16. Add 2–3 Case Studies

**What:** Concrete examples
**Why:** Makes everything understandable

Include:

* one LEG
* one coherent failure
* one hint-fixable case

---

# 🎯 PRIORITY ORDER (do this in order)

1. Evaluation protocol (lock definitions)
2. Core tables (make results undeniable)
3. Reasoning schema (formalize)
4. GitHub + script (reproducibility)
5. Framing rewrite (intro + contributions)
6. Stats (add credibility)
7. CoT comparison (bonus strength)
8. SWE-bench section (external validation)

---

# 🧠 Final sanity check

If someone can:

* run your repo
* reproduce your tables
* understand your categories

👉 you’re in strong shape

If not → rejection risk.

---

# 🔥 Bottom line

You don’t need more ideas.

You need:

> **clarity + reproducibility + sharp framing**

---

If you want, I can next:

* turn this into a **paper outline (section-by-section)**
* or write your **exact contribution bullets + abstract**

That’s the last step to make this land.
