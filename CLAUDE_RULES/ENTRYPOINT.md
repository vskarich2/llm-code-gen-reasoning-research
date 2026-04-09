```markdown

# SYSTEM CONSTRAINTS (NON-NEGOTIABLE)

## Multi-Collaborator Safety

- Do not rename public interfaces without justification
- Do not change schemas without migration logic
- Do not modify config formats silently
- Do not change CLI behavior without instruction

## Dependency Discipline

- Use `uv` for dependency management
- Keep dependencies minimal
- Do NOT introduce heavy or unnecessary dependencies

## Experimental Discipline

- All experiments must be reproducible
- Randomness must be controlled
- All behavior must be config-driven (no hardcoded parameters)

## Decision Rule

When choosing between options:

- prefer minimal change
- prefer explicit over implicit
- prefer safe over clever
- prefer local over global

If uncertain:
→ choose the least invasive correct solution

# RULE EXECUTION PROTOCOL

This is the mandatory execution protocol for all work in this repository.
Every task follows this sequence. No exceptions.

All rule definitions live under `CLAUDE_RULES/`.
This file defines execution order and orchestration only.

If any conflict exists:
→ `INVARIANTS.md` takes precedence.

---

# GLOBAL ARTIFACT MANAGEMENT (MANDATORY)

All generated artifacts MUST be written to the correct directory.

Root:
→ `artifacts/`

Subdirectories:
- plans → `artifacts/plans/`
- analysis → `artifacts/analysis/`
- audits → `artifacts/audits/`
- docs → `artifacts/docs/`
- outputs → `artifacts/outputs/`

## Rules

- NEVER write files outside `artifacts/` unless explicitly modifying existing repo files
- NEVER create duplicate copies of modified source files
- NEVER write files to the root directory

---

## PLAN VERSIONING RULE (STRICT)

Plans MUST follow versioned progression:

- File name must remain consistent
- Versions increment using suffix:
  → `_v1`, `_v2`, `_v3`, ...

- Each revision MUST:
  - be a FULL rewritten plan (no diffs)
  - preserve the same base name
  - be saved in the SAME directory

Example:
```

artifacts/plans/fix_execution_pipeline_v1.md
artifacts/plans/fix_execution_pipeline_v2.md

```

---

## TIMESTAMP REQUIREMENT (MANDATORY)

ALL artifacts MUST include a human-readable timestamp at the top:

Format:
```

Date: YYYY-MM-DD
Time: HH:MM (24h)

```

Applies to:
- plans
- analysis
- audits
- docs

Forbidden:
- missing timestamps
- ambiguous or relative time references

---

## NO RANDOM FILE CREATION

Forbidden:
- writing “temporary” files
- dumping modified code copies
- creating files without explicit purpose

If a file is not:
- a planned artifact
- or a required system file

→ DO NOT CREATE IT

---

# STEP 1 — IDENTIFY TASK TYPE

Classify the current task as exactly one of:
- REFACTOR
- DEBUGGING
- FEATURE

If task-specific rules exist in:
→ `CLAUDE_RULES/tasks/`

Load them.

---

# STEP 2 — LOAD RULE MODULES (MANDATORY ORDER)

Load:

1. `CLAUDE_RULES/INVARIANTS.md`
2. `CLAUDE_RULES/SYSTEM.md`
3. `CLAUDE_RULES/ENGINEERING.md`
4. `CLAUDE_RULES/ANTI_PATTERNS.md`
5. `CLAUDE_RULES/FUNCTIONAL_PROGRAMMING.md`

Then load task-specific rules (if any).

---

# STEP 3 — PRE-ACTION AUDIT (BLOCKING)

Execute:
→ `CLAUDE_RULES/audits/pre_action.md`

Output:
- full checklist
- saved to `artifacts/audits/`

STOP.
Wait for approval.

---

# STEP 4 — PRODUCE A PLAN (BLOCKING)

Write a concrete plan.

Requirements:
- NO code
- specific and minimal
- includes files, functions, risks, tests

Output:
- save to `artifacts/plans/`
- apply versioning rule
- include timestamp

STOP.
Wait for approval.

---

# STEP 5 — EXECUTE CHANGES

After approval:

- implement EXACTLY what was planned
- do NOT expand scope

If new issues arise:
→ STOP
→ return to Step 3

For each file modified:
- state file name
- describe change
- justify safety

---

# STEP 6 — POST-ACTION AUDIT (MANDATORY)

Execute:
→ `CLAUDE_RULES/audits/post_action.md`

Requirements:
- MUST evaluate real code changes
- MUST include evidence
- MUST NOT speculate

Output:
- full report
- save to `artifacts/audits/`
- include timestamp

Rules:
- ANY invariant failure → INVALID
- ANY other failure → MUST FIX

MANDATORY VALIDATION:

Before declaring completion, you MUST run:

    make all

Rules:
- If ANY step fails → the change is INVALID
- You MUST diagnose and fix failures
- You MUST NOT skip or bypass this step
- You MUST report which step failed (lint, typecheck, semgrep, etc.)

Completion is only allowed if:
→ make all passes fully

---

# STEP 7 — CODE PATH / DEBUG AUDIT (STRICT)

If performing debugging or audit:

Execute:
→ `CLAUDE_RULES/audits/code_path_audit.md`

## Ground Truth Requirement

You MUST:
- inspect actual files (logs, outputs, code)
- trace real execution paths
- verify with concrete evidence

Forbidden:
- “likely”
- “possibly”
- “it seems”
- guessing without inspection

All claims MUST reference:
- file
- line
- or concrete artifact

If logs are requested:
→ you MUST read them directly

---

# STEP 8 — COMMIT SUMMARY

Do NOT commit.

Output a commit-ready summary:
- what changed
- why
- tests
- architectural impact

Constraints:
- no first-person
- no process narration
- concise

---

# ENFORCEMENT

- Steps 3 and 4 are BLOCKING
- Step 6 is MANDATORY
- Artifact rules are STRICT
- Anti-pattern violations → immediate rejection
- Invariant violations → system invalid
- No work proceeds under uncertainty

Primary rule:
→ Do not violate INVARIANTS.md
```
