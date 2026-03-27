# RULE EXECUTION PROTOCOL

This is the mandatory execution protocol for all work in this repository.
Every task follows this sequence. No exceptions.

## STEP 1 — IDENTIFY TASK TYPE

Classify the current task as exactly one of:
- REFACTOR (changing existing code structure)
- DEBUGGING (finding and fixing a defect)
- FEATURE (adding new capability)

Load the corresponding task rules from `rules/tasks/`.

## STEP 2 — LOAD RULE MODULES

Always load:
- `rules/core/invariants.md` (hard constraints, never skippable)
- `rules/core/code_quality.md` (function/file limits, naming)
- `rules/core/architecture.md` (module boundaries, data flow)

Then load the task-specific module from Step 1.

## STEP 3 — PRE-ACTION AUDIT

Before writing any code, execute `rules/audits/pre_action.md`:
- List all files that will be modified
- For each file, list functions that will change
- Identify risk of invariant violations
- Identify risk of duplicate code paths
- Identify risk of scope creep

Output the pre-action audit as a checklist. Wait for approval.

## STEP 4 — PRODUCE A PLAN

Write a plan that describes:
- What changes will be made
- Why each change is necessary
- What tests will be added or updated
- What invariants are at risk

The plan must be concrete (file names, function names, line ranges).
No code in the plan. Text only.

Wait for approval before proceeding.

## STEP 5 — EXECUTE CHANGES

After approval:
- Make only the changes described in the plan
- If new issues are discovered, STOP and return to Step 3
- Do not expand scope

For each file modified, state:
- File name
- What changed
- Why it is safe

## STEP 6 — POST-ACTION AUDIT

After all changes, execute `rules/audits/post_action.md`.

Output a rule compliance report in this exact format:

```
RULE COMPLIANCE REPORT
======================
INV-01 Single execution path      PASS
INV-02 No duplicate logic         PASS
INV-03 No silent failures         PASS
INV-04 Config-driven params       FAIL — llm.py:42 hardcoded "gpt-4.1-nano"
CQ-01  Max 50 lines/function      PASS
CQ-02  Max 300 lines/file         FAIL — execution.py has 412 lines
...
```

Every invariant must have PASS or FAIL with evidence.

If any FAIL exists, report it and propose a fix before considering the task complete.

## STEP 7 — COMMIT SUMMARY

Do not commit. Output a commit-ready summary paragraph describing:
- What was changed
- Why it was changed
- What tests were added
- Any architectural considerations

## ENFORCEMENT

- Steps 3 and 4 are BLOCKING. No code before approval.
- Step 6 is MANDATORY. No task is complete without the compliance report.
- If a rule is violated, it must be fixed or explicitly acknowledged by the user.
