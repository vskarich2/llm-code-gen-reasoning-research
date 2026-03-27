# 🔒 CODEBASE RULES (HARD CONSTRAINTS)

These rules are NON-NEGOTIABLE.

Violations are considered CRITICAL ERRORS and must be fixed immediately.

This file exists to PREVENT architectural drift, duplicated logic, silent bugs, and invalid experimental results.

Claude MUST read and comply with ALL rules before writing or modifying any code.

---

## 🧩 ARCHITECTURE RULES

### RULE A1 — SINGLE EXECUTION PATH

❌ FORBIDDEN:
- Multiple top-level execution paths
- Separate “modes” implemented as different pipelines
- Duplicated runner logic (e.g., `run()` vs `_run_mode()`)

✅ REQUIRED:
- EXACTLY ONE canonical execution pipeline
- All variation must be controlled via parameters/config — NOT branching into separate pipelines

📌 RATIONALE:
Multiple execution paths cause divergence, bugs, and invalid experimental comparisons.

---

### RULE A2 — NO DUPLICATE LOGIC

❌ FORBIDDEN:
- Copy-pasting logic across functions
- Slight variations of the same pipeline implemented separately
- Reimplementing existing functionality instead of reusing it

✅ REQUIRED:
- Each logical operation must exist in EXACTLY ONE place

📌 RATIONALE:
Duplication leads to drift and inconsistent behavior.

---

### RULE A3 — CONSOLIDATE, DO NOT FRAGMENT

❌ FORBIDDEN:
- Splitting logic into many small helper functions unnecessarily
- Creating abstraction layers without clear reuse

✅ REQUIRED:
- Prefer consolidation over fragmentation
- Only extract functions when they have a clear, reusable purpose

📌 RATIONALE:
Over-fragmentation hides logic and creates debugging complexity.

---

## 🧱 FUNCTION DESIGN RULES

### RULE F1 — NO LEADING UNDERSCORE FUNCTIONS

❌ FORBIDDEN:
Defining ANY new function with a leading underscore:
- `_helper`
- `_run_*`
- `_process_*`
- `_internal_*`

This includes:
- helpers
- refactors
- “private” functions

✅ REQUIRED:
- All functions must have clear, public, descriptive names

📌 RATIONALE:
Leading underscore functions have repeatedly caused:
- duplicated logic
- shadow execution paths
- architectural drift

🚫 THIS IS ABSOLUTELY UNACCEPTABLE.

---

### RULE F2 — MAX FUNCTION LENGTH = 40 LINES

❌ FORBIDDEN:
- Functions longer than 40 lines

✅ REQUIRED:
- If a function exceeds 40 lines → SPLIT IT into smaller functions

📌 RATIONALE:
Long functions:
- hide bugs
- are hard to reason about
- prevent modular understanding

---

### RULE F3 — DESCRIPTIVE FUNCTION NAMES

❌ FORBIDDEN:
- Vague names (`process`, `handle`, `do_work`, `run_stuff`)
- Abbreviations that obscure meaning

✅ REQUIRED:
- Function names must clearly describe:
  - WHAT the function does
  - WHAT it operates on

📌 EXAMPLES:
- `run_ablation_pipeline` ✅
- `process` ❌

---

### RULE F4 — MANDATORY FUNCTION HEADER COMMENT

❌ FORBIDDEN:
- Defining a function without a comment explaining its purpose

✅ REQUIRED:
Every function MUST have a comment block above it.

Example:

    # Executes the full evaluation pipeline for a single case-condition pair.
    # Handles prompt construction, model call, and evaluation.
    def run_case_pipeline(...):

📌 RATIONALE:
Code must be self-explanatory without reverse engineering.

---

### RULE F5 — NO “JUST IN CASE” FUNCTIONS

❌ FORBIDDEN:
- Creating functions “in case we need this later”
- Premature abstraction

✅ REQUIRED:
- Only create functions that are actively used

---

## 🔁 CONTROL FLOW RULES

### RULE C1 — NO HIDDEN BRANCHING PIPELINES

❌ FORBIDDEN:
- `if mode == X: run_path_A else: run_path_B` where both are full pipelines

✅ REQUIRED:
- One pipeline, parameterized behavior

---

### RULE C2 — NO SILENT FALLBACKS

❌ FORBIDDEN:
- Defaulting silently when required inputs are missing
- Auto-fixing invalid inputs without error

✅ REQUIRED:
- FAIL FAST with explicit errors

---

### RULE C3 — EXPLICIT CONTROL FLOW ONLY

❌ FORBIDDEN:
- Implicit behavior
- Hidden side effects
- Magic defaults

✅ REQUIRED:
- All behavior must be explicit and traceable

---

## 🧪 EXPERIMENTAL INVARIANTS

### RULE E1 — NO DATASET OVERRIDES IN CONTROLLED MODES

❌ FORBIDDEN:
- Allowing CLI overrides that change dataset composition (e.g., `--cases` in ablation mode)

✅ REQUIRED:
- Controlled experiments must use FIXED inputs from config

---

### RULE E2 — IDENTICAL EXECUTION STRUCTURE ACROSS CONDITIONS

❌ FORBIDDEN:
- Changing execution flow between conditions

✅ REQUIRED:
- Same pipeline, same structure, different parameters only

---

## 🛠️ LOGGING & STATE RULES

### RULE L1 — NO DUPLICATE LOGGING SYSTEMS

❌ FORBIDDEN:
- Multiple logging paths for the same event
- “legacy” vs “new” logging behavior

✅ REQUIRED:
- One consistent logging system

---

### RULE L2 — NO SILENT FAILURES

❌ FORBIDDEN:
- Swallowing exceptions
- Missing required fields in outputs

✅ REQUIRED:
- Errors must be explicit and loud

---

## 🚫 PROHIBITED PATTERNS

- Leading underscore functions ❌
- Duplicate pipelines ❌
- Copy-paste logic ❌
- Silent defaults ❌
- Hidden execution paths ❌
- Overly long functions (>40 lines) ❌

---

## ✅ ENFORCEMENT PROTOCOL

Before writing code, Claude MUST:

1. Identify which rules apply  
2. Verify planned changes do NOT violate ANY rule  
3. If a rule would be violated:  
   → STOP  
   → Explain why  
   → Propose an alternative  

---

## ⚠️ FAILURE MODE WARNING

Claude has a strong tendency to:
- introduce helper functions
- duplicate logic across code paths
- create new abstractions instead of reusing existing ones

These behaviors are NOT acceptable.

You MUST prefer:
- consolidation over abstraction
- reuse over creation
- simplicity over fragmentation