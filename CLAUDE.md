# CLAUDE.md — Mandatory Operating Rules

This file is automatically loaded at the start of every conversation.
All rules are non-negotiable.

## RULE SYSTEM

All behavioral rules live in `CLAUDE_RULES/`. Before any task, read and follow:

1. `CLAUDE_RULES/ENTRYPOINT.md` — the mandatory execution protocol (plan → approve → implement → audit)
2. `CLAUDE_RULES/core/invariants.md` — hard constraints (10 invariants, every one checkable)
3. `CLAUDE_RULES/core/code_quality.md` — function/file limits, naming, structure
4. `CLAUDE_RULES/core/architecture.md` — module boundaries, data flow, resource lifecycle
5. `CLAUDE_RULES/core/engineering_constraints.md` — engineering constraints
6. `CLAUDE_RULES/core/functional_programming_constraints.md` — functional programming constraints
7. `CLAUDE_RULES/SYSTEM.md` — system-level rules
8. `CLAUDE_RULES/RULES.md` — additional rules
9. `CLAUDE_RULES/anti_patterns.md` — patterns to avoid
10. `CLAUDE_RULES/tests_required.md` — mandatory test requirements

Task-specific rules:
- `CLAUDE_RULES/tasks/refactor.md`
- `CLAUDE_RULES/tasks/debugging.md`
- `CLAUDE_RULES/tasks/feature_addition.md`

Audit checklists:
- `CLAUDE_RULES/audits/pre_action.md` — run BEFORE writing code
- `CLAUDE_RULES/audits/post_action.md` — run AFTER writing code
- `CLAUDE_RULES/audits/code_path_audit.md` — for tracing execution flow

## PROCESS (always follow)

1. Plan first. No code before a written plan and user approval. 
2. Pre-action audit before implementation.
3. Post-action audit with PASS/FAIL compliance report after implementation.
4. No scope creep. Do exactly what was approved, nothing more.
5. Tests required for every behavioral change.
6. No commits. Provide a commit summary paragraph at the end.

## PLANNING REQUIREMENTS (MANDATORY)

All plans must be persisted to disk and versioned.

- Plans MUST be written to the `artifacts/plans/` directory.
- File naming convention:
  - `artifacts/plans/<task_name>_plan_v1.md`
  - `artifacts/plans/<task_name>_plan_v2.md`
  - `artifacts/plans/<task_name>_plan_v3.md`
- Every revision MUST create a new versioned file. Never overwrite previous versions.
- Version increments must be strictly monotonic (+1 each revision).
- The task_name must be short, descriptive, and stable across revisions.

Plan lifecycle rules:

1. Initial plan:
   - Create `artifacts/plans/<task_name>_plan_v1.md`
   - Must fully specify scope, files touched, invariants, and risks

2. On revision:
   - Create a NEW file: `artifacts/plans/<task_name>_plan_v{N+1}.md`
   - Include:
     - What changed from previous version
     - Why the change was necessary
     - Updated full plan (not a diff-only document)

3. No plan reuse:
   - Never edit an existing plan file
   - Never collapse versions
   - History must remain fully reconstructable

4. Blocking rule:
   - If a plan is not written to `artifacts/plans/` with correct versioning, STOP
   - Do not proceed to implementation

## HARD CONSTRAINTS (memorize these)

- ONE execution path. No parallel pipelines. Config-parameterized variation only.
- No duplicate logic across files.
- No silent failures. Log or raise every exception.
- All experimental parameters from YAML config. Zero hardcoded values.
- No threads. Single-process serial execution.
- No infinite waits. Every network call has an explicit timeout.
- Max 50 lines per function. Max 300 lines per file.
- No new dependencies without explicit approval.

## THIS PROJECT

- Research-grade LLM reasoning benchmark (CS372 final project)
- 6 contributors — no breaking interface changes without migration
- Reproducibility mandatory — seeds, deterministic config, no hidden state
- Use `.venv/bin/python`, not system Python
- Evaluation must be independent of generation (no measurement-intervention blur)

## WHEN UNCERTAIN

- Is this the minimum change needed? If not, reduce scope.
- Am I touching files outside my declared scope? If so, stop and re-plan.
- Does equivalent logic already exist? If so, reuse it.
- Will this pass the post-action audit? If not, redesign.