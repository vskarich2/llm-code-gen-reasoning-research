# SYSTEM.md — LLM Operating Context for CS372 Final Project

This file defines the authoritative operating constraints for any AI assistant  
(Claude Code, Cursor, Copilot-style agents) working in this repository.

This is a research-grade multi-agent reasoning system built for CS372:
Artificial Intelligence for Reasoning, Planning, and Decision-Making.

This is NOT a sandbox.
This is NOT a greenfield rewrite opportunity.
This is NOT a prompt playground.

It is a collaborative research system with 6 contributors.

Precision and restraint are mandatory.

You MUST follow all rules defined in `.claude/RULES.md`.

Violation of any rule is a critical failure.

Before writing any code, you MUST:
1. Read `.claude/RULES.md`
2. Check your planned changes against all rules
3. Explicitly confirm compliance

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. CORE OPERATING PRINCIPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are working inside:

- A shared repository
- A graded research system
- A modular multi-agent architecture
- An evaluation-heavy experimental setup

Your job is to:
- Make minimal, high-quality changes
- Preserve system invariants
- Improve clarity without destabilizing collaborators
- Add tests for every behavioral change
- Never introduce silent breakage

You are not here to “improve everything.”
You are here to make disciplined, traceable modifications.

Restraint > ambition.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. TWO-PHASE PROTOCOL (PLAN → APPROVAL → IMPLEMENT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST follow this protocol for any non-trivial change.

PHASE 1 — PLAN (No code edits allowed)

Before modifying any files, you must:

1. Clearly describe the problem.
2. Identify all files that will be modified.
3. Explain why each file must change.
4. Describe the exact nature of the changes.
5. Describe what tests will be added or updated.
6. Identify potential architectural risks.
7. Confirm that scope is minimal.

You MUST wait for approval before proceeding.

Do NOT modify files during Phase 1.

PHASE 2 — IMPLEMENT

After approval:

- Make only the changes described in the plan.
- If new issues are discovered, stop and re-enter Phase 1.
- Do not silently expand scope.
- Keep changes tightly bounded.

Rule:
No plan → No implementation.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. VERBOSE CHANGE REPORTING (REQUIRED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

During implementation, you MUST:

- State which file is being modified.
- Explain what section is being changed.
- Describe the exact modification.
- Justify why the change is safe.
- Describe the test coverage for the change.

I must be able to follow your progress step-by-step.

Do not silently patch files.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CHANGE DISCIPLINE (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before modifying any file:

1. Identify exactly why the change is required.
2. Confirm which module owns that responsibility.
3. Ensure the change does not violate module boundaries.
4. Avoid touching unrelated files.
5. Do not refactor across the repo unless explicitly instructed.

If a change requires cross-module edits:
- Explain the dependency clearly.
- Keep changes minimal.
- Avoid stylistic rewrites.

Rule:
Do not expand scope implicitly.

Scope creep is a failure mode.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. TESTING REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every behavioral change must include:

- A new unit test OR
- A modification to an existing test OR
- A clear explanation for why no test is needed

All existing tests must pass.

If you modify logic without adding a test,
you are violating operating constraints.

Tests are executable specifications.
They are not optional.

Never weaken tests to make code pass.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. DEPENDENCY & ENVIRONMENT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This repository uses:

- Python
- uv as the dependency manager
- A project-scoped Python environment

You MUST:

- Use uv for dependency management.
- Use the project environment.
- Keep dependencies minimal.
- Only add a dependency if strictly necessary.

You MAY:

- Run read-only scripts without asking permission.
- Install minimal required dependencies using uv without asking permission.

You MUST NOT:

- Introduce heavy or unnecessary dependencies.
- Change environment structure.
- Use pip directly instead of uv.
- Modify lockfiles unnecessarily.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7. ARCHITECTURAL BOUNDARIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Respect module responsibilities.

Common modules include:

- Agent definitions
- Debate orchestration
- Evaluation modules (CRIT / RCA / T3 / etc.)
- Logging / trace capture
- Experiment runner
- Config management
- Tests

Rules:

- Evaluation modules must not mutate debate logic.
- Debate agents must not manipulate scoring logic.
- Experimental harness must not contain business logic.
- No circular imports.
- No hidden side effects.

If unsure: isolate the change.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8. MULTI-COLLABORATOR SAFETY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This repository has 6 contributors.

Therefore:

- Do not rename public interfaces lightly.
- Do not change JSON schema without migration logic.
- Do not modify config formats silently.
- Do not change CLI behavior without instruction.
- Preserve backward compatibility unless explicitly told otherwise.

If a breaking change is required:
- Flag it clearly.
- Propose a minimal migration path.
- Keep surface area small.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
9. EVALUATION MODULE SPECIAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Evaluation logic must be:

- Deterministic where possible
- Reproducible
- Configurable
- Explicit about scoring assumptions
- Free of hidden heuristics

CRIT / RCA / T3 scoring logic must:

- Avoid leaking debate information improperly
- Avoid modifying raw model outputs
- Separate measurement from intervention
- Support clean ablation

Never blur evaluation with generation.

Measurement integrity is critical.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
10. EXPERIMENTAL RIGOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is a CS372 system project emphasizing:

- Architectural clarity
- Evaluation rigor
- Failure analysis
- Modular reasoning components

Therefore:

- All experiments must be reproducible.
- Random seeds must be controllable.
- Config must be externally settable.
- No hardcoded experimental parameters.

Research integrity > convenience.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
11. GIT & COMMIT DISCIPLINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST NOT commit any changes.

You MUST NOT create commits.
You MUST NOT push branches.
You MUST NOT modify git history.

You will only modify files locally.

At the end of implementation, you MUST output:

A clean commit message summary paragraph (3–4 sentences),
written in neutral repository tone,
summarizing:

- What was changed
- Why it was changed
- What tests were added or updated
- Any architectural considerations

Do NOT reference yourself.
Do NOT use first person.
Do NOT describe the process.
Just provide a concise commit-ready summary paragraph.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
12. WHEN IN DOUBT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before implementing:

- Am I increasing complexity unnecessarily?
- Am I touching more files than required?
- Am I adding abstraction without benefit?
- Am I weakening tests?
- Am I changing semantics unintentionally?

If uncertain:
Propose the minimal safe version.

Restraint is preferred over ambition.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
13. SUMMARY FOR FAST PARSING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Two-phase protocol required
- Plan first, implement after approval
- Verbose progress reporting
- Minimal changes
- No scope creep
- Tests required
- Respect architecture
- Use uv only
- No heavy dependencies
- Do not commit
- Provide commit summary paragraph
- Reproducibility is mandatory
- Stability > cleverness

END SYSTEM CONTEXT.