# CODE PATH AUDIT

Use this audit to trace execution flow, debug hangs, or verify that a variable or resource behaves correctly.

This is a diagnostic tool for detecting violations of INVARIANTS.md.

---

# STEP 1 — DEFINE THE SUBJECT

State exactly what you are tracing:

- Variable: "where does `eval_model` come from?"
- Flow: "what happens when an API call times out?"
- Resource: "where is the client created and destroyed?"

---

# STEP 2 — TRACE ALL PRODUCERS

Find every place the subject is created, assigned, or modified.

List:
`file:line — description`

---

# STEP 3 — TRACE ALL CONSUMERS

Find every place the subject is used, read, or terminated.

Include:
- reads
- returns
- raises
- cleanup

List:
`file:line — description`

---

# STEP 4 — ANALYZE FLOW INTEGRITY

Check:

- Are all producers intentional and consistent?
- Are there conflicting producers?
- Does every path lead to a valid consumer?
- Are there dead paths (never reached)?
- Are there missing paths (unhandled states)?
- Is lifecycle complete (for resources)?

---

# STEP 5 — REPORT
CODE PATH AUDIT: {subject}

Producers:

{file}:{line} — {description}
...

Consumers:

{file}:{line} — {description}
...

Consistent flow: YES | NO
Conflicts: {description or "none"}
Dead paths: {description or "none"}
Missing paths: {description or "none"}
Lifecycle issues: {description or "none"}


---

# RULE

If flow is:
- conflicting
- incomplete
- duplicated without intent

→ system behavior is unreliable
→ likely violates INVARIANTS.md