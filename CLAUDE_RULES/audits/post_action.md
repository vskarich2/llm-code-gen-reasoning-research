# POST-ACTION AUDIT

Execute this audit AFTER all changes are complete.
Output the full compliance report. Every line must have PASS or FAIL.

## INVARIANT COMPLIANCE

For each invariant, check the CHANGED FILES ONLY:

```
INV-01 Single execution path        PASS | FAIL — evidence
INV-02 No duplicate logic           PASS | FAIL — evidence
INV-03 No silent failures           PASS | FAIL — evidence
INV-04 Config-driven parameters     PASS | FAIL — evidence
INV-05 No hardcoded fallbacks       PASS | FAIL — evidence
INV-06 Deterministic execution      PASS | FAIL — evidence
INV-07 Eval-gen separation          PASS | FAIL — evidence
INV-08 Complete logging             PASS | FAIL — evidence
INV-09 No threads                   PASS | FAIL — evidence
INV-10 No infinite waits            PASS | FAIL — evidence
```

## CODE QUALITY COMPLIANCE

For each changed file:

```
CQ-01 Max 50 lines/function         PASS | FAIL — {file}:{function} has {N} lines
CQ-02 Max 300 lines/file            PASS | FAIL — {file} has {N} lines
CQ-03 Descriptive function names    PASS | FAIL — {file}:{function} is vague
CQ-04 Docstrings on public funcs    PASS | FAIL — {file}:{function} missing docstring
CQ-05 No magic numbers              PASS | FAIL — {file}:{line} literal {N}
CQ-06 Max 3 nesting levels          PASS | FAIL — {file}:{line} nesting depth {N}
CQ-07 No dead code                  PASS | FAIL — {file}:{function} never called
CQ-08 Import hygiene                PASS | FAIL — {file} unused import {module}
```

## ARCHITECTURE COMPLIANCE

```
ARCH-01 Module responsibility       PASS | FAIL — {function} placed in wrong module
ARCH-02 Data flow direction         PASS | FAIL — {file} imports from downstream {module}
ARCH-03 Single source of truth      PASS | FAIL — {state} has multiple owners
ARCH-04 No global mutable state     PASS | FAIL — {file}:{line} mutable module-level {var}
ARCH-05 Resource lifecycle          PASS | FAIL — {resource} created without cleanup
ARCH-06 No cross-module side effects PASS | FAIL — {file} mutates {module}.{var}
ARCH-07 File placement              PASS | FAIL — {function} belongs in {correct_module}
```

## SCOPE VERIFICATION

```
SCOPE-01 Only declared files changed    PASS | FAIL — unexpected change to {file}
SCOPE-02 No feature creep               PASS | FAIL — {description of extra change}
SCOPE-03 Tests added/updated            PASS | FAIL — no tests for {change}
```

## SUMMARY

Total checks: {N}
Passed: {N}
Failed: {N}

If any FAIL: list each with proposed fix.
