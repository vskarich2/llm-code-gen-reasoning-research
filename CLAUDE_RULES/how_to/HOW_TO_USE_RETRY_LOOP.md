Good—this is the moment to lock in a **clean mental model + workflow**.
Right now you’ve built something powerful, but if the workflow isn’t crisp, you won’t use it.

I’m going to give you the **exact loop you should follow**, no fluff.

---

# 🧠 Your system = 3 modes

You now operate in **three distinct modes**:

```text
1. THINK (chat / planning)
2. PROPOSE (ce --dry-run)
3. COMMIT (ce accept)
```

If you blur these, the system breaks down.

---

# 🔥 Your actual workflow (step-by-step)

## ✅ Step 0 — (optional) think in chat

Use Claude however you want:

```text
"what’s wrong with this code?"
"how should I fix this?"
```

👉 This is exploration. No constraints.

---

## ✅ Step 1 — run a dry-run

```bash
ce "fix tokenizer merge bug" --dry-run
```

### What happens:

* model proposes diff
* scope enforced
* evaluator runs
* retry loop kicks in if needed
* result is saved to `.ce_last.json`

You see:

```diff
diff --git ...
```

and:

```json
{
  "task_correct": true,
  "suspicious": false
}
```

---

## 🧠 Decision point (THIS is critical)

You now decide:

### Case A — ❌ bad diff

You DO NOT accept.

You refine:

```bash
ce "fix tokenizer merge bug but avoid modifying config.py" --dry-run
```

or let retry loop handle it.

---

### Case B — ✅ good diff

Now you move to commit.

---

## ✅ Step 2 — accept

```bash
ce accept
```

### What happens:

* reuses exact diff (no LLM call)
* applies patch
* runs tests
* creates branch + PR

---

## ✅ Step 3 — review PR (final gate)

On GitHub:

* sanity check
* merge

---

# 🔁 Full loop (condensed)

```text
chat (optional)
   ↓
ce --dry-run
   ↓
inspect diff
   ↓
ce accept
   ↓
PR → merge
```

---

# 🔥 For larger work (plan-based)

## Step 1 — plan

```bash
plan_to_json PLAN.md
```

---

## Step 2 — execute step-by-step

```bash
ce step 1 --plan plan.json --dry-run
ce accept

ce step 2 --plan plan.json --dry-run
ce accept
```

---

# ⚠️ Rules you should follow (non-negotiable)

## 1. Never skip dry-run

Bad:

```bash
ce "fix bug"
```

Good:

```bash
ce "fix bug" --dry-run
```

---

## 2. Never accept blindly

You MUST:

* read diff
* sanity check

---

## 3. Never manually paste code

Always go through pipeline.

---

## 4. Keep tasks small

Bad:

```bash
ce "refactor whole execution system"
```

Good:

```bash
ce "fix incorrect condition in retry loop"
```

---

# 🧠 What your system is actually doing

You are NOT:

> “asking Claude to write code”

You ARE:

> **running a constrained search over diffs with validation + feedback**

---

# 🔥 Why this workflow is strong

You now have:

* deterministic execution (`accept`)
* controlled generation (`dry-run`)
* automatic retries
* enforced scope
* full logging

This is basically:

> a mini research platform for code generation

---

# ⚠️ The biggest mistake you can make now

You’ll be tempted to go back to:

```text
“this is small, I’ll just edit manually”
```

Don’t.

That destroys:

* consistency
* logs
* your ability to analyze

---

# 🧠 One-liner mental model

```text
dry-run = proposal
accept = commit
```

---

# 🚀 What you do next (very concrete)

Run this:

```bash
ce "fix something small in your repo" --dry-run
```

Then:

```bash
ce accept
```

Go through the full loop once.

That’s how it clicks.

---
