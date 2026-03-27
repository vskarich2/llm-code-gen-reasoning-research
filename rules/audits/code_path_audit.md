# CODE PATH AUDIT

Use this audit when investigating execution flow, debugging hangs, or verifying
that a critical variable has exactly one code path.

## STEP 1 — IDENTIFY THE CRITICAL VARIABLE OR FLOW

State exactly what you are tracing:
- A variable (e.g., "where does `eval_model` come from?")
- A code path (e.g., "what happens when an API call times out?")
- A resource (e.g., "where is the OpenAI client created and destroyed?")

## STEP 2 — TRACE ALL PRODUCERS

For a variable: find every place it is assigned or modified.
For a code path: find every branch that can reach it.
For a resource: find every constructor call.

List each as: `file:line — description`

## STEP 3 — TRACE ALL CONSUMERS

For a variable: find every place it is read.
For a code path: find every place it exits (return, raise, crash).
For a resource: find every place it is used and every place it is closed.

List each as: `file:line — description`

## STEP 4 — VERIFY SINGLE PATH

For the critical flow:
- Is there exactly one producer? If not, which ones conflict?
- Is there exactly one consumer path? If not, which ones diverge?
- Are there any dead paths (code that is never reached)?
- Are there any missing paths (states that are never handled)?

## STEP 5 — REPORT

Output:

```
CODE PATH AUDIT: {subject}
================================
Producers:
  1. {file}:{line} — {description}
  2. ...

Consumers:
  1. {file}:{line} — {description}
  2. ...

Single path: YES | NO
Conflicts: {description or "none"}
Dead paths: {description or "none"}
Missing paths: {description or "none"}
```
