# TASK TYPE: FEATURE ADDITION

Rules specific to adding new capabilities.

## FEAT-01 — Design Before Code

Before writing any code:
1. Describe what the feature does
2. Describe how it integrates with existing modules (reference ARCH-01 module map)
3. Describe what config parameters it requires
4. Describe what tests it needs
5. Describe what existing behavior it might affect

Wait for approval.

## FEAT-02 — Config First

If the feature introduces any tunable parameter:
- Add it to the YAML config schema first
- Wire the config into the code
- No hardcoded values

This applies to: model names, thresholds, timeouts, file paths, feature flags.

## FEAT-03 — Test Simultaneously

Write tests alongside the feature, not after.
The feature is not complete until tests pass.

Minimum test coverage:
- Happy path (normal inputs, expected output)
- Error path (invalid inputs, expected failure)
- Edge case (boundary values, empty inputs)

## FEAT-04 — No Infrastructure Sprawl

Before adding a new dependency (pip package, external service, database):
1. Justify why it is strictly necessary
2. Identify the simplest alternative that avoids the dependency
3. If the dependency is approved, document how to install and run it

Do not introduce Docker, new databases, or new network services without explicit approval.

## FEAT-05 — Rollback Path

Every feature must be removable.
Identify what to delete or revert to remove the feature cleanly.
No feature should create permanent coupling that cannot be undone.

## FEAT-06 — Documentation

After implementation, provide:
- How to use the feature (CLI flags, config keys)
- What it does (one paragraph)
- What it does NOT do (scope boundary)
