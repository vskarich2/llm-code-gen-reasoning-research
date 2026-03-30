# Oracle Stress Test Results

Generated: 2026-03-28 18:46:25 UTC

## Summary

- Total buggy variants: 22
- Total correct variants: 15
- Buggy correctly rejected: 22/22
- Correct correctly accepted: 15/15

## Per-Case Results

### alias_config_a

- Buggy fail rate: 100.0%
- Correct pass rate: 100.0%

**Buggy variants:**

| # | Failure Type | Oracle Correct | Status |
|---|-------------|----------------|--------|
| 0 | shared_reference_direct | PASS | exec=failed |
| 1 | cosmetic_refactor_no_fix | PASS | exec=failed |
| 2 | docstring_enhancement_no_fix | PASS | exec=failed |
| 3 | copies_then_mutates_original | PASS | exec=failed |
| 4 | caching_alias | PASS | exec=failed |

**Correct variants:**

| # | Description | Oracle Correct | Status |
|---|------------|----------------|--------|
| 0 | Uses dict() constructor to copy | PASS | exec=passed |
| 1 | Uses ** unpacking to copy | PASS | exec=passed |
| 2 | Uses .copy() method -- reference fix approach | PASS | exec=passed |

### alias_config_b

- Buggy fail rate: 100.0%
- Correct pass rate: 100.0%

**Buggy variants:**

| # | Failure Type | Oracle Correct | Status |
|---|-------------|----------------|--------|
| 0 | original_bug_unchanged | PASS | exec=failed |
| 1 | adds_feature_misses_bug | PASS | exec=failed |
| 2 | copy_then_mutate_defaults | PASS | exec=failed |
| 3 | memoization_over_alias | PASS | exec=failed |

**Correct variants:**

| # | Description | Oracle Correct | Status |
|---|------------|----------------|--------|
| 0 | Uses .copy() in create_config -- reference fix app | PASS | exec=passed |
| 1 | Uses dict() constructor -- LLM's actual approach | PASS | exec=passed |
| 2 | Uses ** unpacking with inline merge | PASS | exec=passed |

### mutable_default_a

- Buggy fail rate: 100.0%
- Correct pass rate: 100.0%

**Buggy variants:**

| # | Failure Type | Oracle Correct | Status |
|---|-------------|----------------|--------|
| 0 | original_mutable_default | PASS | exec=failed |
| 1 | module_level_shared_list | PASS | exec=failed |
| 2 | validation_without_fix | PASS | exec=failed |
| 3 | function_attr_shared_list | PASS | exec=failed |

**Correct variants:**

| # | Description | Oracle Correct | Status |
|---|------------|----------------|--------|
| 0 | Standard fix: None sentinel with fresh list -- ref | PASS | exec=passed |
| 1 | Functional style: creates new list via concatenati | PASS | exec=passed |
| 2 | Uses list() constructor instead of [] literal | PASS | exec=passed |

### stale_cache_a

- Buggy fail rate: 100.0%
- Correct pass rate: 100.0%

**Buggy variants:**

| # | Failure Type | Oracle Correct | Status |
|---|-------------|----------------|--------|
| 0 | original_no_invalidation | PASS | exec=failed |
| 1 | refactored_no_invalidation | PASS | exec=failed |
| 2 | cache_on_add_not_update | PASS | exec=failed |
| 3 | logging_no_invalidation | PASS | exec=failed |
| 4 | versioning_no_invalidation | PASS | exec=failed |

**Correct variants:**

| # | Description | Oracle Correct | Status |
|---|------------|----------------|--------|
| 0 | Invalidates cache on update via pop -- reference f | PASS | exec=passed |
| 1 | Refreshes cache with updated data instead of inval | PASS | exec=passed |
| 2 | Uses del to remove cache entry if present | PASS | exec=passed |

### partial_update_a

- Buggy fail rate: 100.0%
- Correct pass rate: 100.0%

**Buggy variants:**

| # | Failure Type | Oracle Correct | Status |
|---|-------------|----------------|--------|
| 0 | original_no_sync | PASS | exec=failed |
| 1 | generic_update_no_sync | PASS | exec=failed |
| 2 | allowlist_no_sync | PASS | exec=failed |
| 3 | comment_defers_responsibility | PASS | exec=failed |

**Correct variants:**

| # | Description | Oracle Correct | Status |
|---|------------|----------------|--------|
| 0 | Syncs display_name in the name branch -- reference | PASS | exec=passed |
| 1 | If-block style with display_name sync -- LLM's act | PASS | exec=passed |
| 2 | Extracts sync logic into helper function called af | PASS | exec=passed |
