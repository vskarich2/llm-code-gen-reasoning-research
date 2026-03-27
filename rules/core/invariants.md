# HARD INVARIANTS

These constraints are non-negotiable. Every invariant is checkable.
Violation of any invariant must be reported in the post-action audit.

## INV-01 — Single Execution Path

There must be exactly ONE canonical execution pipeline.
No parallel implementations. No "legacy" vs "new" paths.
All variation is controlled by config parameters, not branching into separate pipelines.

Check: grep for `if.*mode.*==` patterns that dispatch to entirely different execution functions.

## INV-02 — No Duplicate Logic

Each logical operation must exist in exactly one place.
No copy-paste across functions. No slight variations of the same computation in different files.

Check: search for functions with similar names or similar bodies across files.

## INV-03 — No Silent Failures

Every exception must be either:
- re-raised, or
- logged with sufficient context to diagnose

Forbidden:
- `except: pass`
- `except Exception: pass`
- `except Exception as e:` followed by no log and no raise

Check: grep for `except.*:` and verify each has a log or raise.

## INV-04 — Config-Driven Parameters

Every experimental parameter must come from the YAML config.
No hardcoded model names, temperatures, retry counts, token budgets,
truncation limits, or timeout values in execution code.

Check: grep for string literals matching model name patterns (`gpt-`, `claude-`, `o1-`, etc.) in .py files outside of configs/ and tests/.

## INV-05 — No Hardcoded Fallback Defaults

If a required config value is missing, the system must crash with an explicit error.
No `value = config.get("key", "some_default")` for experimental parameters.

Check: grep for `config.get(` with default values in execution-critical code paths.

## INV-06 — Deterministic Execution

All experimental runs must be reproducible given the same config and seed.
No unseeded randomness. No time-dependent behavior in evaluation logic.
No dependence on iteration order of unordered collections.

Check: grep for `random.` without preceding `random.seed()`. Grep for `dict.keys()` used in ordering-sensitive contexts.

## INV-07 — Evaluation-Generation Separation

Evaluation code must never mutate generation inputs or outputs.
Generation code must never read evaluation results.
Measurement must be independent of intervention.

Check: verify evaluation modules do not import from generation modules, and vice versa, except through defined interfaces.

## INV-08 — Complete Logging

Every evaluation attempt must produce a complete log record.
No evaluation may complete without writing to the run log.
Timed-out or crashed evaluations must produce a terminal failure record.

Check: verify every code path through `run_single`, `run_repair_loop`, `run_contract_gated`, `run_leg_reduction` ends with a `write_log` call or an exception handler that records the failure.

## INV-09 — No Threads

The system is single-process, single-threaded, serial execution.
No `ThreadPoolExecutor`. No `threading.Thread`. No `concurrent.futures`.
Parallelism is achieved by launching separate processes externally.

Check: grep for `ThreadPoolExecutor`, `threading.Thread`, `concurrent.futures` in execution code.

## INV-10 — No Infinite Waits

Every network call must have an explicit timeout.
No call to an external service (OpenAI API, Redis, HTTP) may block indefinitely.

Check: verify every `OpenAI()` constructor has a `timeout` parameter. Verify every Redis client has `socket_timeout`. Verify no `requests.get()` or `urllib` call lacks a timeout.
