# CLAUDE.md — Mandatory Operating Rules

This file is automatically loaded at the start of every conversation.
All rules are non-negotiable.

## RULE SYSTEM

All behavioral rules live in `rules/`. Before any task, read and follow:

1. `rules/ENTRYPOINT.md` — the mandatory execution protocol (plan → approve → implement → audit)
2. `rules/core/invariants.md` — hard constraints (10 invariants, every one checkable)
3. `rules/core/code_quality.md` — function/file limits, naming, structure
4. `rules/core/architecture.md` — module boundaries, data flow, resource lifecycle

Task-specific rules:
- `rules/tasks/refactor.md`
- `rules/tasks/debugging.md`
- `rules/tasks/feature_addition.md`

Audit checklists:
- `rules/audits/pre_action.md` — run BEFORE writing code
- `rules/audits/post_action.md` — run AFTER writing code
- `rules/audits/code_path_audit.md` — for tracing execution flow

## PROCESS (always follow)

1. Plan first. No code before a written plan and user approval.
2. Pre-action audit before implementation.
3. Post-action audit with PASS/FAIL compliance report after implementation.
4. No scope creep. Do exactly what was approved, nothing more.
5. Tests required for every behavioral change.
6. No commits. Provide a commit summary paragraph at the end.

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
