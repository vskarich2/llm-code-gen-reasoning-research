# ============================================================
# CLAUDE RULES — CANONICAL INVARIANTS + ENFORCEMENT
# ============================================================

This document defines:
1) System invariants (non-negotiable properties)
2) Operational invariants (config + change discipline)
3) Architectural invariants (pipeline structure + separation)
4) Static enforcement rules (Semgrep)

Violations:
- MUST be surfaced
- MUST include root cause
- MUST block approval unless explicitly waived

---

# ============================================================
# HARD INVARIANTS
# ============================================================

# INV-01 — Single Canonical Execution Entry

Definition:
Exactly one entrypoint orchestrates:
- prompt construction
- model invocation
- parsing
- reconstruction
- execution evaluation
- reasoning evaluation
- logging

Requirements:
- All execution flows route through this entry
- Retries re-enter this entry

Forbidden:
- Multiple run/evaluate entrypoints
- Direct downstream calls bypassing execution layer

---

# INV-02 — Single Canonical Implementation Per Responsibility

Applies to:
- parsing
- reconstruction
- evaluation
- retry control
- logging
- metrics

Requirements:
- One implementation per responsibility

Forbidden:
- v2 / alt / fallback duplicate logic

---

# INV-03 — No Silent Failure

Definition:
All failures must be:
- raised (invariant violations), or
- logged explicitly (recoverable)

Forbidden:
- bare except
- except: pass
- silent fallbacks

---

# INV-04 — Explicit Contract Boundaries

Requirements:
- validate all inputs
- enforce output structure
- distinguish missing vs invalid vs empty

Forbidden:
- unchecked dict access
- implicit assumptions

---

# INV-05 — No Silent Defaults for Critical Values

Requirements:
- required values must be validated

Forbidden:
- config.get("x", default) for required fields

---

# INV-06 — Controlled Determinism

Requirements:
- seeded randomness
- deterministic ordering
- no time-based logic

Forbidden:
- unseeded randomness
- reliance on dict/set ordering

---

# INV-07 — Separation of Generation and Evaluation

Requirements:
- no mutation of generated artifacts
- feedback must be explicit and logged

Forbidden:
- hidden feedback loops
- evaluator modifying generation

---

# INV-08 — Complete Terminal Logging

Requirements:
- exactly one terminal state per attempt
- must always be logged
- logs must allow full reconstruction of behavior

---

# INV-09 — No Unbounded External Calls

Requirements:
- all external calls have timeouts
- failure modes must be logged

---

# INV-10 — Explicit Resource Lifecycle

Requirements:
- clear ownership
- explicit creation + cleanup

Forbidden:
- unmanaged clients
- unclosed resources

---

# INV-11 — Single Source of Truth for State

Requirements:
- compute once, propagate forward

Forbidden:
- shadow copies
- recomputation inconsistencies

---

# INV-12 — Raw Artifact Preservation

Requirements:
- store raw prompts, responses, outputs
- transformations must be logged separately

Forbidden:
- overwriting raw data

---

# INV-13 — Metric Provenance Integrity

Requirements:
- label metrics:
  - behavioral (trusted)
  - classifier (heuristic)
  - derived

Forbidden:
- mixing trust levels without labeling

---

# INV-14 — No Duplicate Decision Logic

Requirements:
- single owner for:
  - retry policy
  - classification thresholds
  - evaluation criteria

---

# INV-15 — Integration Integrity

Requirements:
- full pipeline tests required
- no unit-only validation for pipeline changes
- end-to-end behavior must be verified after any change

---

# ============================================================
# ARCHITECTURAL INVARIANTS — PIPELINE & SEPARATION
# ============================================================

# INV-16 — Canonical Pipeline Structure

All evaluation must follow a single canonical pipeline:

orchestrator
→ execution entrypoint
→ prompt construction
→ model invocation
→ parsing
→ reconstruction
→ execution evaluation (behavioral)
→ reasoning evaluation (semantic)
→ logging

Requirements:
- all stages must exist explicitly
- ordering must be preserved
- no stage may be skipped

Forbidden:
- skipping stages
- collapsing multiple stages into one implicit step
- embedding pipeline logic across unrelated modules

---

# INV-17 — No Pipeline Bypass

All system flow must pass through the canonical execution entry.

Requirements:
- downstream modules are only accessed through the execution layer
- no direct cross-module shortcuts

Forbidden:
- calling parsing, evaluation, or logging outside the canonical flow
- recomputing results outside the pipeline
- reconstructing state independently in other modules

---

# INV-18 — Strict Stage Separation

The following concerns must remain strictly separated:

- parsing → what the model produced
- reconstruction → mapping structure to program representation
- execution → behavioral correctness
- reasoning evaluation → semantic correctness

Requirements:
- each stage has a distinct implementation
- each stage logs its own output and status

Forbidden:
- parser repairing or completing missing data
- reconstructor silently fixing parse errors
- evaluator executing code
- execution layer performing reasoning classification

---

# ============================================================
# OPERATIONAL INVARIANTS — CONFIG & CHANGE DISCIPLINE
# ============================================================

# INV-19 — Configuration Single Source of Truth

Definition:
All configuration MUST originate from YAML.

Requirements:
- YAML is the only configuration source
- config is read-only and passed downward

Forbidden:
- defaults in Python code
- shadow config systems
- implicit overrides

---

# INV-20 — Configuration Propagation Integrity

Definition:
All config values must propagate end-to-end.

Requirements:
- YAML → loader → execution → subsystems → logging
- no silent drops
- unused config values must be detected

Forbidden:
- ignored config fields
- implicit overrides
- partial propagation

---

# INV-21 — Configuration Observability

Definition:
All behavior influenced by config must be observable.

Requirements:
- config-driven behavior must be logged
- logs must allow attribution of outcomes to config

Forbidden:
- hidden config effects
- behavior changes not reflected in logs

---

# INV-22 — End-to-End Change Integrity

Definition:
All changes must preserve full pipeline correctness.

Requirements:
- changes must be traced across:
  - prompt assembly
  - model call
  - parsing
  - reconstruction
  - execution
  - evaluation
  - metrics
  - logging

Forbidden:
- partial updates
- stage-local validation only

---

# INV-23 — No Partial Updates

Definition:
System changes must be globally consistent.

Requirements:
- modifying one component requires validating all downstream dependencies

Forbidden:
- isolated changes without system-wide verification

---

# ============================================================
# STATIC ENFORCEMENT — SEMGREP RULESET
# ============================================================

rules:

# ============================================================
# INV-03 — NO SILENT FAILURE
# ============================================================

- id: no-bare-except
  pattern: |
    try:
      ...
    except:
      ...
  message: "Bare except is forbidden (INV-03)"
  severity: ERROR
  languages: [python]

- id: no-except-pass
  pattern: |
    try:
      ...
    except ...:
      pass
  message: "Silent exception handling is forbidden (INV-03)"
  severity: ERROR
  languages: [python]

- id: exception-must-raise-or-log
  patterns:
    - pattern: |
        try:
          ...
        except $E:
          ...
    - pattern-not: |
        try:
          ...
        except $E:
          raise
    - pattern-not: |
        try:
          ...
        except $E:
          logging.$X(...)
    - pattern-not: |
        try:
          ...
        except $E:
          logger.$X(...)
  message: "Exceptions must be raised or logged (INV-03)"
  severity: WARNING
  languages: [python]

# ============================================================
# INV-06 — DETERMINISM
# ============================================================

- id: no-unseeded-random
  patterns:
    - pattern-either:
        - pattern: random.random(...)
        - pattern: np.random.$F(...)
    - pattern-not-inside: random.seed(...)
    - pattern-not-inside: np.random.seed(...)
  message: "Randomness must be seeded (INV-06)"
  severity: ERROR
  languages: [python]

# ============================================================
# INV-11 — NO GLOBAL STATE
# ============================================================

- id: no-global-state
  pattern: global $X
  message: "Global state is forbidden (INV-11)"
  severity: ERROR
  languages: [python]

# ============================================================
# INV-04 — CONTRACT SAFETY
# ============================================================

- id: missing-return-type
  patterns:
    - pattern: |
        def $FUNC(...):
            ...
    - pattern-not: |
        def $FUNC(...) -> ...:
            ...
  message: "Missing return type annotation (INV-04)"
  severity: WARNING
  languages: [python]

- id: return-without-validation
  patterns:
    - pattern: |
        def $FUNC(...):
            ...
            return $X
    - pattern-not: |
        def $FUNC(...):
            ...
            assert ...
            return $X
    - pattern-not: |
        def $FUNC(...):
            ...
            validate($X)
            return $X
  message: "Return must be validated (INV-04)"
  severity: WARNING
  languages: [python]

# ============================================================
# INV-05 — NO SILENT DEFAULTS
# ============================================================

- id: no-required-get-default
  pattern: config.get($KEY, $DEFAULT)
  message: "Avoid defaults for required config (INV-05)"
  severity: WARNING
  languages: [python]

# ============================================================
# INV-07 — NO HIDDEN MUTATION
# ============================================================

- id: mutable-default-args
  pattern-either:
    - pattern: def $F(..., $X=[], ...): ...
    - pattern: def $F(..., $X={}, ...): ...
  message: "Mutable default arguments forbidden (INV-07)"
  severity: ERROR
  languages: [python]

# ============================================================
# INV-10 — RESOURCE LIFECYCLE
# ============================================================

- id: file-open-no-context
  pattern: open($F, "w")
  message: "Use context manager for file writes (INV-10)"
  severity: WARNING
  languages: [python]

# ============================================================
# INV-04 — LOGGING DISCIPLINE
# ============================================================

- id: no-print
  pattern: print(...)
  message: "Use structured logging (INV-04)"
  severity: WARNING
  languages: [python]

# ============================================================
# INV-02 — COMPLEXITY / DUPLICATION SIGNALS
# ============================================================

- id: deep-nesting
  pattern: |
    if ...:
      if ...:
        if ...:
          if ...:
            ...
  message: "Excessive nesting (INV-02 risk)"
  severity: WARNING
  languages: [python]

- id: magic-number
  pattern: $X = $NUM
  metavariable-pattern:
    metavariable: $NUM
    pattern: [0-9]{2,}
  message: "Magic number detected"
  severity: WARNING
  languages: [python]

# ============================================================
# END
# ============================================================