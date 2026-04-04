# Leading Whitespace Recovery — Plan v1

## Problem

gpt-5-mini adds a leading space character to JSON file values ~8-20% of the time. The code itself is valid Python, but `ast.parse()` raises `SyntaxError: unexpected indent (<unknown>, line 1)`. This causes RECON_INVALID_CODE for otherwise correct fixes.

Three variants observed:
- **67/68 cases**: Single leading space on line 1 only (e.g., ` import os\ndef foo(): ...`)
- **1/68 cases**: Entire code indented 4 spaces (module-level code as if inside a class body)
- **0 cases in nano/4o-mini**: Exclusively a gpt-5-mini behavior

## Scope

### Files modified (2):
1. `core/pipeline/reconstructor.py` — add `textwrap.dedent()` recovery step in `_normalize_file_content()`
2. `core/tests/test_reconstruction_logging.py` — add tests for leading-whitespace recovery

### Files NOT modified:
- No dashboard changes
- No config changes
- No prompt changes
- No execution pipeline changes

## Design

### Recovery step placement

Add after existing normalization (fence strip, unescape, prefix strip) and before the `return` in `_normalize_file_content()`:

```
existing: fence strip → unescape \\n → prefix strip
new:      fence strip → unescape \\n → prefix strip → dedent leading whitespace
```

### Logic

```python
import textwrap

# After all other normalization, dedent if leading whitespace present
if normalized and normalized[0] in (' ', '\t'):
    dedented = textwrap.dedent(normalized)
    if dedented != normalized:
        normalized = dedented
        leading_whitespace_stripped = True
```

### Recovery tracking

- Recovery type: `"leading_whitespace_stripped"`
- Normalization log entry: `"leading_whitespace_stripped:{rel_path}"`
- Follows exact same pattern as `fence_stripped` and `file_value_prefix_stripped`

### Return value

`_normalize_file_content()` currently returns `tuple[str, bool]` where bool = prefix_stripped. The function will return a third value or we modify to return a richer signal. Since reconstruct_strict already checks `normalized != value` and then checks specific conditions (fence, unescape, prefix), adding a new condition for dedent follows the same pattern.

Actually, looking at the code: `_normalize_file_content` returns `(normalized, prefix_stripped)`. The caller in `reconstruct_strict` then separately checks `normalized != value` and inspects the original value to determine which recovery type applies. The dedent case is detectable by checking `normalized != pre_dedent_value` or by returning an additional flag.

**Cleanest approach**: Add a `leading_ws_stripped` bool to the return tuple → `tuple[str, bool, bool]`. This keeps the detection inside the normalizer where it belongs.

## Tests (4 new)

1. `test_dedent_single_leading_space` — single space on line 1, rest at column 0
2. `test_dedent_full_indent` — all lines indented 4 spaces (the ordering_dependency case)
3. `test_no_dedent_clean_python` — already-clean code is not modified
4. `test_reconstruct_tracks_leading_whitespace_strip` — end-to-end through `reconstruct_strict`, verifies recovery_types contains `"leading_whitespace_stripped"`

## Invariants

- No new dependencies (textwrap is stdlib)
- No config changes needed
- Recovery is tracked, never silent
- Existing tests must still pass (prefix_stripped bool position unchanged — actually it changes to index [1] in a 3-tuple, so callers must be updated)

## Risks

- Changing `_normalize_file_content` return type from 2-tuple to 3-tuple requires updating all callers. There is exactly one caller: `reconstruct_strict` at line 317.
- `textwrap.dedent()` removes *common* leading whitespace. For the single-leading-space case (67/68), this correctly removes the one space from line 1 (since it's the only line with extra indent). For the all-indented case (1/68), it correctly removes the common 4-space prefix. No false positives expected — if the code is already at column 0, dedent is a no-op.
