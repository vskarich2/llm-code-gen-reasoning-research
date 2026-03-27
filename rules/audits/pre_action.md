# PRE-ACTION AUDIT

Execute this audit BEFORE writing any code.
Output the checklist in full. Wait for approval before proceeding.

## 1. SCOPE CHECK

- [ ] List every file that will be modified
- [ ] List every function that will be added, changed, or deleted
- [ ] Confirm no files outside this list will be touched

## 2. DUPLICATE LOGIC CHECK

- [ ] For each new function: does equivalent logic already exist elsewhere?
- [ ] If yes: reuse the existing function instead of creating a new one
- [ ] For each modified function: will this create a second implementation of the same logic?

## 3. INVARIANT RISK CHECK

- [ ] INV-01 (single path): does this change create a parallel execution path?
- [ ] INV-02 (no duplicates): does this change duplicate any existing logic?
- [ ] INV-03 (no silent failures): does this change introduce any unlogged exception handling?
- [ ] INV-04 (config-driven): does this change introduce any hardcoded parameters?
- [ ] INV-09 (no threads): does this change introduce threading or concurrency?
- [ ] INV-10 (no infinite waits): does this change make network calls? If so, are timeouts set?

## 4. ARCHITECTURE CHECK

- [ ] Which module owns this change? (reference ARCH-01 module map)
- [ ] Does the change respect data flow direction? (ARCH-02)
- [ ] Does the change create any new global mutable state? (ARCH-04)
- [ ] Does the change create any new external resources? If so, what is the cleanup path? (ARCH-05)

## 5. SCOPE CREEP CHECK

- [ ] Is the planned change the MINIMUM required to achieve the goal?
- [ ] Are there any "while I'm here" improvements included? If so, remove them.
- [ ] Can the change be split into smaller independent steps?

## 6. TEST PLAN

- [ ] What tests will be added or modified?
- [ ] What existing tests might break?
- [ ] How will the change be verified?
