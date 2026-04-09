```markdown id="audit-v2"
# POST_ACTION_AUDIT

Execute AFTER all changes are complete.

Output a full compliance report.
Each line MUST be: PASS or FAIL with evidence.

Audit applies ONLY to changed files.

---

# 1. INVARIANT COMPLIANCE

Check against INVARIANTS.md.

```

INV-01 Execution entrypoint integrity     PASS | FAIL — evidence
INV-02 No duplicate implementations       PASS | FAIL — evidence
INV-03 No silent failure                  PASS | FAIL — evidence
INV-04 Contract enforcement               PASS | FAIL — evidence
INV-05 No silent defaults                 PASS | FAIL — evidence
INV-06 Determinism preserved              PASS | FAIL — evidence
INV-07 Generation/evaluation separation   PASS | FAIL — evidence
INV-08 Terminal logging completeness      PASS | FAIL — evidence
INV-09 Bounded external calls             PASS | FAIL — evidence
INV-10 Resource lifecycle                 PASS | FAIL — evidence
INV-11 Single source of truth (local)     PASS | FAIL — evidence
INV-12 Raw artifact preservation          PASS | FAIL — evidence
INV-13 Metric provenance clarity          PASS | FAIL — evidence
INV-14 Centralized decision logic         PASS | FAIL — evidence
INV-15 Integration integrity              PASS | FAIL — evidence
INV-16 Pipeline structure preserved       PASS | FAIL — evidence
INV-17 No pipeline bypass                 PASS | FAIL — evidence
INV-18 Stage separation preserved         PASS | FAIL — evidence
INV-19 Config source integrity            PASS | FAIL — evidence
INV-20 Config propagation                 PASS | FAIL — evidence
INV-21 Config observability               PASS | FAIL — evidence
INV-22 End-to-end consistency             PASS | FAIL — evidence
INV-23 No partial updates                 PASS | FAIL — evidence

```

---

# 2. ENGINEERING COMPLIANCE

Check against ENGINEERING.md.

```

EC-01 Explicit contracts              PASS | FAIL — evidence
EC-02 Fail-fast boundaries            PASS | FAIL — evidence
EC-03 Function size & responsibility  PASS | FAIL — evidence
EC-04 File scope discipline           PASS | FAIL — evidence
EC-05 Control flow simplicity         PASS | FAIL — evidence
EC-06 No hidden side effects          PASS | FAIL — evidence
EC-07 Reuse before new code           PASS | FAIL — evidence
EC-08 Correct placement               PASS | FAIL — evidence
EC-09 Testability                     PASS | FAIL — evidence
EC-10 Minimal/local changes           PASS | FAIL — evidence
EC-11 Naming clarity                  PASS | FAIL — evidence
EC-12 Import hygiene                  PASS | FAIL — evidence
EC-13 Docstrings present              PASS | FAIL — evidence
EC-14 No magic numbers                PASS | FAIL — evidence

```

---

# 3. ANTI-PATTERN CHECK

Check against ANTI_PATTERNS.md.

```

AP-01 No silent failure patterns      PASS | FAIL — evidence
AP-02 No hidden state                PASS | FAIL — evidence
AP-03 No mutable defaults            PASS | FAIL — evidence
AP-04 No implicit failure paths      PASS | FAIL — evidence
AP-05 Input validation present       PASS | FAIL — evidence
AP-06 No duplicate logic introduced  PASS | FAIL — evidence
AP-07 No hidden side effects         PASS | FAIL — evidence
AP-08 No pipeline bypass             PASS | FAIL — evidence

```

---

# 4. SCOPE VERIFICATION

```

SCOPE-01 Only declared files changed     PASS | FAIL — evidence
SCOPE-02 No scope creep                  PASS | FAIL — evidence
SCOPE-03 Tests added/updated             PASS | FAIL — evidence

```

---

# 5. SUMMARY

```

Total checks: {N}
Passed: {N}
Failed: {N}

```

If any FAIL:
- list each failure
- include root cause
- propose minimal fix

---

# RULE

If any invariant FAILS:
→ change is INVALID

If engineering or anti-pattern FAILS:
→ fix required before approval
```

