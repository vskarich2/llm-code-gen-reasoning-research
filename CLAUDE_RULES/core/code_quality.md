# CODE QUALITY CONSTRAINTS

Enforceable limits on code structure and implementation discipline. Each constraint has a numeric threshold or clear audit rule.

---

## CQ-01 — Max 40 Lines Per Function

Preferred maximum: 30 lines  
Soft maximum: 40 lines  
Absolute maximum: 50 lines (requires explicit justification in plan)

- Count non-blank, non-comment lines between `def` and the next `def` or end of file.
- Functions exceeding 40 lines must be split into smaller units.

---

## CQ-02 — Max 300 Lines Per File

No Python file in the execution pipeline may exceed 300 lines.

- Preferred maximum: 250 lines
- Files must have a single dominant responsibility.
- If multiple unrelated concerns exist, split the file even if under 300 lines.

Excluded:
- test files
- analysis scripts
- legacy code in `_archive/`

Check: `wc -l` on each `.py` file.

---

## CQ-03 — Descriptive, Specific Function Names

Function names must clearly encode:
- action (verb)
- object (what is acted on)
- context (if needed)

Forbidden:
- `process`, `handle`, `do_work`, `run_stuff`, `helper`

Acceptable:
- `build_evaluation_prompt`
- `parse_model_response_json`
- `reconstruct_code_files_from_dict`
- `compute_pass_rate`

If a function performs multiple logical steps, it must be split — not renamed.

Check:
- Flag vague or single-word names in execution code.

---

## CQ-04 — Mandatory Contract-Level Docstrings

Every function called outside its module must have a docstring.

Docstring must include:
- purpose
- inputs (types + required fields)
- outputs (structure)
- failure conditions
- side effects (if any)

Check:
- grep for `def ` and verify `"""` within 2 lines
- manual audit for completeness

---

## CQ-05 — No Magic Numbers

Numeric literals in execution logic must be named constants or config values.

Forbidden:
- `if score > 0.95:`
- `text[:800]`
- `timeout=600`

Acceptable:
- `if score > PASS_THRESHOLD:`
- `text[:config.max_chars]`

Rules:
- All thresholds must be centralized
- Constants must encode semantic meaning

Excluded:
- 0, 1, -1
- loop bounds in test code

Check:
- grep for numeric literals > 1 not assigned to named constants

---

## CQ-06 — Max 3 Levels of Nesting

No code block may exceed 3 levels of nesting.

Preferred maximum: 2 levels

Requirement:
- Extract nested logic into helper functions when depth > 2
- Use guard clauses to flatten control flow

Check:
- indentation depth analysis

---

## CQ-07 — No Dead Code or Duplicate Logic

Forbidden:
- commented-out code blocks
- unreachable branches
- unused functions
- duplicate logic across files

Rules:
- duplicate logic must be consolidated into a single implementation
- legacy paths must be removed, not preserved

Check:
- grep for commented code patterns
- cross-reference function definitions with call sites

---

## CQ-08 — Import Hygiene

- No wildcard imports (`from x import *`)
- No unused imports
- No circular imports between execution modules

Check:
- `pylint` or equivalent
- manual verification of module dependencies

---

## CQ-09 — Single Responsibility Per Function

Each function must perform exactly one logical operation.

Allowed responsibilities:
- validate
- parse
- transform
- assemble
- route
- evaluate
- log
- compute

Forbidden:
- parse + validate + mutate in one function
- orchestration mixed with transformation logic
- multi-step hidden pipelines

Check:
- function name vs body mismatch
- presence of multiple distinct operations

---

## CQ-10 — No Silent Failure

Functions must not silently recover from invalid states.

Forbidden:
- returning default values for invalid input
- swallowing exceptions
- partial success returns
- implicit fallback behavior

Required:
- explicit error or assertion on invalid state

Examples (forbidden):
- `dict.get("key", [])` when key is required
- `return None` for failure without contract

---

## CQ-11 — Explicit Input Validation

All external inputs must be validated at function boundaries.

Includes:
- dict keys
- types
- required fields

Forbidden:
- assuming keys exist
- implicit coercion of malformed data
- passing unchecked external input deeper into the system

Check:
- presence of validation logic at entry points

---

## CQ-12 — No Implicit Mutation

Functions must not mutate input arguments unless explicitly documented.

Preferred:
- return new objects

Forbidden:
- modifying caller-owned dicts/lists without contract
- hidden state changes

Check:
- mutation patterns in functions
- absence of mutation documentation

---

## CQ-13 — Centralized Constants Only

All shared constants must come from a single source of truth.

Includes:
- thresholds
- condition names
- status labels
- category values

Forbidden:
- redefining constants across files
- hardcoded string labels in multiple locations

Check:
- scan for repeated literals across modules

---

## CQ-14 — Logging at Critical Boundaries

Functions that:
- transform data
- change execution state
- call external systems

must emit structured logs.

Minimum logging requirements:
- operation name
- identifiers (`run_id`, `case_id`, etc.)
- success/failure status
- relevant metadata

Forbidden:
- silent transformations
- missing logs at key boundaries

Check:
- trace critical execution paths and verify log presence

---

# SUMMARY

This file enforces:
- bounded complexity
- clear structure
- explicit contracts
- no silent failure
- no duplication
- strong observability

Code that is clean but:
- duplicates logic
- hides failures
- mutates state implicitly
- lacks validation
- cannot be audited

is non-compliant.