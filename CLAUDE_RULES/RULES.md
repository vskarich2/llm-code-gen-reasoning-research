# CODEBASE RULES — STRICT INVARIANTS (V2)

## 0. OVERARCHING PRINCIPLE

This system is CONFIG-DRIVEN, SINGLE-PATH, AND FULLY EXPLICIT.

Any behavior that is:
- implicit
- duplicated
- partially applied
- silently dropped

is a system bug.

There are NO exceptions.

---

## 1. SINGLE SOURCE OF TRUTH — CONFIGURATION

### 1.1 YAML IS THE ONLY SOURCE OF CONFIGURATION

ALL configuration knobs MUST originate from the YAML config.

STRICTLY FORBIDDEN:
- Default values inside Python files
- Shadow configs (execution_config.py, eval_config.py, etc.)
- Fallback values hidden in code paths
- “Optional overrides” that bypass YAML

ALLOWED:
- Reading from YAML
- Passing config through functions
- Using config values as inputs ONLY

RULE:
> If a parameter exists, it MUST exist FIRST in YAML and NOWHERE ELSE.

Violation = HARD FAILURE.

---

### 1.2 NO DERIVED CONFIG WITHOUT EXPLICIT DECLARATION

If a value is computed from config:
- It MUST be explicitly defined as a derived field
- The transformation MUST be visible and traceable

NO:
- hidden transformations
- inline magic numbers
- implicit conversions

---

### 1.3 CONFIG ACCESS IS READ-ONLY

Code MUST NOT mutate config.

Config is:
- immutable
- passed downward
- never rewritten

---

## 2. CONFIG PLUMBING INTEGRITY (MANDATORY)

Whenever a new config knob is introduced, the following MUST be verified:

### 2.1 FULL PIPELINE PROPAGATION

The knob MUST be:

YAML → Loader → Execution → Subsystems → Logging (if relevant)

NO breaks allowed.

You MUST verify:
- It is loaded correctly
- It is passed to every component that depends on it
- It is not silently ignored anywhere

---

### 2.2 ZERO SILENT DROPS

If a config value:
- is defined but unused
- is passed but ignored
- is overridden implicitly

This is a SYSTEM BUG.

You MUST:
- detect it
- log it
- or fail loudly

---

### 2.3 LOGGING REQUIREMENT

If a config knob affects:
- execution behavior
- evaluation behavior
- output generation
- control flow

It MUST be logged.

Logs must allow:
- reconstruction of behavior
- attribution of outcomes to config

If a knob changes behavior but is not observable in logs → INVALID SYSTEM STATE

---

## 3. CORE EXECUTION PATH INTEGRITY

### 3.1 SINGLE CANONICAL EXECUTION PATH

There is ONE execution path.

STRICTLY FORBIDDEN:
- parallel pipelines
- alternate “shortcuts”
- condition-specific logic branches duplicating behavior

All variation must be:
→ parameterized via config
→ not implemented via separate code paths

---

### 3.2 CHANGE PROPAGATION REQUIREMENT (MANDATORY)

Any change to the core execution path MUST be:

1. Traced end-to-end
2. Verified across all stages
3. Confirmed not to break invariants

You MUST explicitly verify:

- Prompt assembly still receives correct inputs
- LLM call receives correct payload
- Parser still matches expected schema
- Reconstruction still validates outputs
- Execution still runs correct code
- Evaluation still receives correct signals
- Metrics still computed correctly
- Logs still reflect full state

If ANY stage is inconsistent → CHANGE IS INVALID

---

### 3.3 NO PARTIAL UPDATES

You are NOT allowed to modify:
- one stage
- one function
- one module

WITHOUT verifying downstream impact.

Partial updates = corruption.

---

### 3.4 STRUCTURAL INVARIANTS MUST HOLD

After any change:
- inputs == expected schema
- outputs == expected schema
- contracts == satisfied

No drift allowed.

---

## 4. FAILURE HANDLING

### 4.1 NO SILENT FAILURES

All failures MUST:
- raise
- or log explicitly with context

STRICTLY FORBIDDEN:
- try/except pass
- fallback defaults
- masking errors

---

### 4.2 FAIL FAST ON INCONSISTENCY

If:
- config is missing
- config is unused
- config is miswired
- execution path is broken

→ HARD FAIL immediately

---

## 5. NO DUPLICATION

### 5.1 CONFIG LOGIC

There must NEVER be:
- multiple config systems
- duplicated config definitions
- shadow defaults

---

### 5.2 EXECUTION LOGIC

No duplicated:
- pipelines
- evaluators
- parsing logic
- reconstruction logic

One implementation ONLY.

---

## 6. TESTING REQUIREMENTS

Every change MUST validate:

### 6.1 CONFIG INTEGRITY
- New knobs appear in YAML
- Knobs propagate correctly
- No silent drops

### 6.2 EXECUTION INTEGRITY
- End-to-end pipeline still works
- No stage mismatch

### 6.3 LOGGING INTEGRITY
- Behavior is reconstructable
- Config influence is visible

---

## 7. DELETION POLICY

DO NOT delete:
- unused configs
- templates
- modules

UNLESS:
- confirmed dead
- not referenced anywhere
- explicitly approved

History is preserved.

---

## 8. ENFORCEMENT SUMMARY

You MUST guarantee:

1. YAML is the ONLY config source
2. Every knob is fully propagated or rejected
3. No silent drops, ever
4. All core path changes are end-to-end verified
5. No partial updates
6. No duplicate logic
7. No silent failures

If any of these are violated:
→ The system is invalid
→ The change must be rejected

---