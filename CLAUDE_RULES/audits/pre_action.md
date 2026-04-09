# PRE-ACTION AUDIT

Execute BEFORE writing any code.
Output the checklist in full.
Wait for approval before proceeding.

This audit ensures planned changes will not violate INVARIANTS.md, ENGINEERING.md, or ANTI_PATTERNS.md.

---

# 1. SCOPE DEFINITION

- [ ] List every file that will be modified
- [ ] List every function that will be added, changed, or deleted
- [ ] Confirm no files outside this list will be touched

---

# 2. DUPLICATION RISK

- [ ] Does equivalent logic already exist?
- [ ] If yes: reuse instead of creating new logic
- [ ] Will this introduce a second implementation of the same responsibility?

---

# 3. INVARIANT RISK CHECK

- [ ] Could this change introduce a parallel execution path?
- [ ] Could this change bypass the canonical pipeline?
- [ ] Could this introduce silent failure or unhandled states?
- [ ] Could this introduce hidden state or mutation?
- [ ] Could this break determinism?
- [ ] Could this break logging completeness or traceability?
- [ ] Could this break config integrity or propagation?

If ANY answer is unclear:
→ STOP and resolve before implementation

---

# 4. ARCHITECTURE & OWNERSHIP

- [ ] Which module owns this responsibility?
- [ ] Is the change placed in the correct module?
- [ ] Does this violate separation of concerns?
- [ ] Does this introduce cross-module coupling?
- [ ] Does this introduce new resources? If so, what is their lifecycle?

---

# 5. SCOPE DISCIPLINE

- [ ] Is this the MINIMUM change required?
- [ ] Is any unrelated improvement included? If yes, remove it
- [ ] Can this be split into smaller steps?

---

# 6. TEST PLAN

- [ ] What tests will be added or updated?
- [ ] What failure modes are covered?
- [ ] How will correctness be verified end-to-end?

---

# RULE

If:
- scope is unclear
- ownership is unclear
- invariant risk is unclear

→ DO NOT IMPLEMENT
→ return to planning