# TASK TYPE: DEBUGGING

Rules specific to finding and fixing defects.

## DBG-01 — Prove Before Fix

Before changing any code:
1. State the hypothesis for what is causing the defect
2. Describe the evidence that supports the hypothesis
3. Describe what evidence would disprove the hypothesis
4. Add instrumentation to confirm the hypothesis
5. Run with instrumentation and capture results
6. Only after confirmation, propose the fix

No speculative fixes. No "fix all three possible causes at once."

## DBG-02 — Single Fix Per Iteration

Apply exactly one fix at a time.
Verify the fix resolves the defect.
Only then consider whether additional changes are needed.

Multiple simultaneous fixes make it impossible to determine which one worked.

## DBG-03 — Minimal Change

The fix must be the smallest change that resolves the defect.
Do not refactor surrounding code. Do not improve style. Do not add features.

If surrounding code needs improvement, that is a separate REFACTOR task.

## DBG-04 — Regression Test

Every bug fix must include a test that:
- Fails before the fix
- Passes after the fix
- Prevents the same defect from recurring

## DBG-05 — Root Cause Documentation

After the fix, document:
- What the defect was
- What caused it
- What the fix is
- Why the fix is correct
- What test prevents recurrence
