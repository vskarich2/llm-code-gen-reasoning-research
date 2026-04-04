# Oracle Schema Enrichment Audit

## PHASE 1: SCHEMA AUDIT

### Existing fields that cover Oracle needs directly:
- `ground_truth_bug.type` → maps to `bug_type`
- `ground_truth_bug.location` → maps to `bug_location`
- `trap` → normalizes to `trap_description`

### Fields missing entirely (must be authored):
- `mechanism_source` — not derivable from existing fields
- `mechanism_property` — not derivable (invariant is close but too prescriptive)
- `mechanism_steps` — not derivable (description is one sentence, not structured)
- `mechanism_outcome` — not derivable (failure_mode is a category, not a description)

### Fields derivable mechanically:
- `bug_type` ← `ground_truth_bug.type` (direct copy)
- `bug_location` ← `ground_truth_bug.location` (direct copy, but needs cross-check against reference_fix)
- `trap_description` ← `trap` (normalize "No trap" to null)

### Fields requiring case-by-case authoring:
- `mechanism_source` — 58 cases
- `mechanism_property` — 58 cases
- `mechanism_steps` — 58 cases (variable length)
- `mechanism_outcome` — 58 cases

### Schema change:
New field `oracle_ground_truth` at case root level, containing all 7 fields.

### Naming convention:
snake_case, consistent with existing benchmark fields.

### Validation rules:
- `bug_type`: non-empty string
- `bug_location`: non-empty string
- `mechanism_source`: non-empty string
- `mechanism_property`: non-empty string
- `mechanism_steps`: list of strings, length >= 1
- `mechanism_outcome`: non-empty string
- `trap_description`: string or null
