# Assembly Pipeline Forensic Audit

## 1. Executive Verdict

The code assembly system is **architecturally unsound**. It flattens multi-file
Python programs into a single namespace via string concatenation, then rewrites
import aliases without checking for name collisions. This creates infinite recursion
when a model writes `from X import Y as Z` and then defines a function with the
same name `Y`. The alias `Z` is silently renamed to `Y`, making the function call
itself.

This is **not a local bug**. It is a **fundamental flaw in the flattening model**.
The assembler destroys Python module semantics (separate namespaces, import
resolution, binding scopes) and replaces them with a string-concatenation heuristic
that is provably unsound for any code that relies on cross-module name isolation.

The current assembly system **cannot be trusted** for multi-file cases where models
write modular, delegation-style code. It systematically penalizes better coding
practices and rewards cruder, inlined implementations.

**121 evaluations across 9 cases** are confirmed contaminated. **17% of gpt-5-mini
failures** in the main 4-model ablation are assembly artifacts, not model failures.

---

## 2. Actual Assembly Pipeline

The hot path for every v2 evaluation:

```
runner.py:_run_one_inner()
  → execution_v2.py:run_v2()
    → reconstructor.py:reconstruct_strict()     # extract per-file code from JSON
      → returns dict of {filepath: code_string}
    → join changed files with "\n\n"             # FIRST FLATTENING: files → single string
    → exec_eval.py:exec_evaluate(case, code)
      → exec_eval.py:_assemble_program(code, case)
        → code_assembly.py:CodeAssembler().assemble(model_code, case)
          → IF len(code_files_contents) <= 1:
              _process_imports(model_code, ...)   # single-file: strip imports only
          → ELSE:
              _assemble_multi_file(...)           # multi-file: full pipeline
                1. Load originals from code_files_contents
                2. Normalize (strip fences, unescape)
                3. Validate syntax per-file
                4. _process_imports() on each file  → _rewrite_imports_safe()
                   → AST parse
                   → _collect_import_info()
                   → Build rename_map: {alias → original_name}  ← THE BUG
                   → _ImportRemover: strip import statements
                   → _NameRewriter: rename all alias occurrences
                   → ast.unparse()
                5. CONCATENATE: originals + "\n\n" + model  ← SECOND FLATTENING
                6. _resolve_qualified_imports()  (for import X; X.attr patterns)
                7. compile() validation
      → exec_eval.py:load_module_from_code(assembled_code)
        → exec(compile(code, ...), mod.__dict__)   ← SINGLE NAMESPACE EXECUTION
      → test_fn(mod)                               ← RUN INVARIANT TEST
```

**There is ONE execution path.** No fallback. No module-based alternative on the
hot path. `module_exec.py` exists but is a side-channel for analysis only — its
results never affect pass/fail scoring.

---

## 3. Architectural Inventory

| Strategy | Location | Active? | Used by | Safe? |
|---|---|---|---|---|
| **Namespace flattening** (concat + exec) | code_assembly.py + exec_eval.py | **YES — canonical** | All evaluations | **NO** |
| AST import rewriting ("safe" mode) | code_assembly.py:_rewrite_imports_safe | **YES** | Multi-file assembly | **NO** (alias collision) |
| Line-based stripping ("compat" mode) | code_assembly.py:_strip_imports_compat | Available but not default | Legacy | **NO** (different issues) |
| Qualified import resolution (SimpleNamespace) | code_assembly.py:_resolve_qualified_imports | **YES** | `import X; X.attr` patterns | Partially safe |
| Module-based execution | module_exec.py | **NO** (side-channel only) | Comparison analysis | Safe but unused |
| Real Python import system | Not implemented | **NO** | Nothing | N/A |

**The fundamental problem:** There is no path in the evaluation pipeline that
preserves Python module boundaries. Every multi-file evaluation flattens all code
into one namespace.

---

## 4. Root Cause of the Recursion Bug

### Minimal reproducer

**Input:** `effect_order_b` case (2 files: metrics.py, processor.py)

**Original metrics.py:**
```python
def reset():
    global _counter, _events
    _counter = 0
    _events = []
```

**Model output (gpt-5-mini style):**
```python
from metrics import increment, emit_event, reset as metrics_reset

def reset():
    metrics_reset()  # Delegate to metrics module's reset
```

### Assembly transformation

Step 4 processes the model code with `_rewrite_imports_safe()`:

1. Finds `from metrics import reset as metrics_reset` (local import with alias)
2. Adds to `rename_map`: `{"metrics_reset": "reset"}` — **NO collision check**
3. Strips the import statement
4. `_NameRewriter` visits every `ast.Name` node, replacing `metrics_reset` with `reset`

**Before rewrite:**
```python
def reset():
    metrics_reset()
```

**After rewrite:**
```python
def reset():
    reset()  # ← INFINITE RECURSION
```

Step 5 concatenates:
```python
# From metrics.py (original)
def reset():
    global _counter, _events
    _counter = 0
    _events = []

# From processor.py (original, import-stripped)
def reset():           # shadows metrics.reset
    ...

# From model code (rewritten)
def reset():           # shadows both above
    reset()            # calls itself
```

Step 7 (exec): Python's last-definition-wins. The final `reset()` is the one
that calls itself. **Infinite recursion.**

### Verification

```python
>>> from code_assembly import CodeAssembler
>>> result = CodeAssembler().assemble(model_code, case)
>>> result.status
'SUCCESS'          # Assembly reports SUCCESS despite creating broken code
>>> result.assembly_risky
True               # Detects duplicate defs but doesn't prevent execution
```

The assembler **detects** the duplicate definition (`assembly_risky=True`) but
**does not detect** that the rename created a self-call. It reports `SUCCESS`
and passes the broken code to `exec()`.

---

## 5. Why the Module System Did Not Prevent It

**There is no module system on the hot path.** The evaluation pipeline uses
namespace flattening exclusively. `module_exec.py` exists as a separate analysis
tool but:

- It is never called from `exec_evaluate()`
- It is never called from `run_v2()`
- It is never called from any retry harness
- Its results never affect pass/fail scoring
- It has no integration with `CodeAssembler`

The module execution path was built for comparison analysis (e.g.,
`test_dual_execution.py` tests it), but it was **never wired into the evaluation
pipeline**. The flattening path is and always has been canonical.

---

## 6. Test Failure Analysis

### Tests that exist

- `test_code_assembly.py::TestAliasRewriting::test_from_import_as_rewritten`:
  Tests that `from X import Y as Z` correctly renames Z→Y. **But only tests
  the case where Y is NOT redefined locally.** The test passes because there
  is no collision.

- `test_code_assembly.py::TestCollisions`: Tests qualified import collisions
  (`import X; import Y; X.reset() Y.reset()`). **Does NOT test alias rename
  collisions.**

- `test_assembly.py::TestAssemblyFunction::test_duplicate_defs_detected`:
  Verifies `assembly_risky=True` when model redefines an original function.
  **But does not check whether the assembly is semantically broken.**

### The missing test

No test covers this scenario:

```python
# Original file: metrics.py
def reset():
    ...

# Model code:
from metrics import reset as metrics_reset
def reset():
    metrics_reset()  # Should call metrics.reset, not self
```

This specific pattern — **aliased import where the alias is renamed to collide
with a local redefinition** — has zero test coverage. None of the 50+ assembly
tests, 60+ integration tests, or 58-case parametrized tests cover it.

### Why it slipped through

1. Reference fixes don't use this pattern. The hand-written fixes use direct
   global variable access (`global _counter; _counter = 0`) rather than
   module delegation. So the integration tests (which run reference fixes
   through the full pipeline) never trigger the collision.

2. The assembly unit tests test alias rewriting in isolation, without the
   concatenation step that creates the collision.

3. `assembly_risky=True` is set but **never blocks execution**. The flag is
   informational only. No test validates that risky assemblies produce correct
   behavior.

### Required tests to prevent recurrence

1. **Alias-collision test**: Model writes `from X import Y as Z; def Y(): Z()`.
   Assert the assembled code does NOT create self-recursion.
2. **Semantic-preservation test**: Run same model code through flattening AND
   module execution. Assert identical behavior.
3. **Recursion detector**: Post-assembly AST scan for functions that call
   themselves when the self-call was introduced by renaming.

---

## 7. Other Potential Assembly Anomalies

| Class | Status | Description |
|---|---|---|
| **Alias-rename self-recursion** | **CONFIRMED** | `from X import Y as Z; def Y(): Z()` → recursion |
| **Execution order dependence** | **LIKELY** | Original code concatenated before model code. Module-level side effects in originals execute first. |
| **Stale bindings** | **LIKELY** | `_fn = imported_func` captured before model redefines `imported_func`. Stale reference persists. |
| **Name shadowing across files** | **CONFIRMED** | Multiple files defining `reset()` — last definition wins silently. `assembly_risky` set but not enforced. |
| **Star import collisions** | **POSSIBLE** | `from X import *` removed, but if X and Y both define `foo`, only the last survives. No warning. |
| **Module-level initialization order** | **LIKELY** | If original file has `_config = load()` at module level, it executes before model's redefined `load()` is available. |
| **Circular import semantics altered** | **POSSIBLE** | Circular imports work in Python via partial module loading. Flattening eliminates this mechanism entirely. |
| **Class inheritance across files** | **POSSIBLE** | If model redefines base class, subclass in another file may inherit wrong version depending on concatenation order. |
| **Import-as-value capture** | **POSSIBLE** | `X = __import__('metrics')` or `importlib.import_module()` not handled by AST rewriter. |

---

## 8. Contamination Audit

### Scope

| Metric | Value |
|---|---|
| Total rows scanned | 9,239 |
| Total recursion errors | 121 (1.31%) |
| Affected cases | 9 of 58 (16%) |
| Affected models | Primarily gpt-5-mini (117/121 = 97%) |

### By case

| Case | Errors | Models |
|---|---|---|
| effect_order_b | 71 | gpt-5-mini (69), gpt-5.4-mini (2) |
| retry_dup_c | 24 | gpt-5-mini |
| effect_order_c | 10 | gpt-5-mini |
| partial_rollback_b | 7 | gpt-5-mini |
| partial_rollback_c | 3 | gpt-5-mini |
| async_race_lock | 2 | nano (1), 4o-mini (1) |
| use_before_set_c | 2 | gpt-5-mini |
| retry_dup_b | 1 | gpt-5-mini |
| use_before_set_b | 1 | gpt-5-mini |

### Impact on main ablation (v2_full_4model_5trial)

- gpt-5-mini: 33 of 192 failures (17%) are recursion artifacts
- Affected cases: effect_order_b (11), retry_dup_c (11), effect_order_c (5),
  partial_rollback_b (3), partial_rollback_c (2), retry_dup_b (1)
- gpt-5-mini's true failure count: 159, not 192. True pass rate: ~82% not ~78%

### Systematic bias

**The contamination is systematically biased against modular code.** gpt-5-mini
writes `from X import Y as Z; def Y(): Z()` (correct delegation pattern) while
weaker models write `def Y(): global _var; _var = 0` (crude inlining). The
assembler rewards the crude pattern and punishes the correct one.

This means:
- gpt-5-mini's pass rate is **artificially depressed** by ~4pp on multi-file cases
- The BL-LEG gap analysis for gpt-5-mini may be slightly distorted (if LEG
  conditions trigger different import patterns than baseline)
- Family-level effects for SIDE_EFFECT_ORDER and RETRY_DUPLICATION are overstated
  as "hard" when they're partly assembly artifacts
- The finding that "stronger models have smaller BL-LEG gaps" may be slightly
  understated (gpt-5-mini is actually doing better than measured)

### Conclusions that are NOT affected

- gpt-5.4-mini results (only 2 recursion errors)
- gpt-4.1-nano results (only 1 recursion error)
- gpt-4o-mini results (only 1 recursion error)
- The capability threshold finding (still holds after correction)
- The retry ablation results (different log directories, mostly clean)
- The critique specificity finding (clean data)
- The "bare retry helps" finding (clean data)
- Single-file case results (not affected by assembly)

---

## 9. Fix Recommendation

### Temporary containment (do immediately)

1. **Tag contaminated rows.** Add `assembly_recursion_artifact: true` to the 121
   affected evaluations. Filter them from all analysis.

2. **Add post-assembly recursion detector.** After `_rewrite_imports_safe()`, scan
   the AST for any function that calls itself where the self-call was introduced
   by renaming (not present in the original code). If detected, set
   `status = "REWRITE_ERROR"` instead of `"SUCCESS"`.

3. **Add collision check to rename_map.** Before adding `alias → original_name`,
   check if `original_name` is already defined as a function/class in any assembled
   file. If yes, skip the rename and keep the alias. Log a warning.

### Real fix (architectural)

**Delete namespace flattening. Use real module execution.**

The flattening model is fundamentally unsound. No amount of AST rewriting can
faithfully preserve Python module semantics in a single namespace. The correct
approach:

1. Execute each file in its own namespace (via `exec()` with a separate dict).
2. Wire cross-module imports by injecting the source module's namespace as a
   module object in `sys.modules` before executing the importing file.
3. Process files in dependency order (topological sort on import graph).

This is what `module_exec.py` already does (partially). The fix is to make it
the canonical execution path instead of a side-channel.

**Estimated effort:** Medium. The module execution logic exists. The main work is:
- Making it the default in `exec_evaluate()`
- Handling the model-code-overrides-original-file case (model's processor.py
  replaces the original processor.py in the module graph)
- Updating tests to cover the new path
- Deprecating the flattening path

### What should be deleted

- `_rewrite_imports_safe()` — unsound by design
- `_strip_imports_compat()` — even less sound
- The concatenation step in `_assemble_multi_file()` — the root of all problems
- The `_NameRewriter` — blind renaming without scope analysis

### What should remain

- `_resolve_qualified_imports()` — the SimpleNamespace approach is sound for its
  narrow use case, but should be replaced by real module loading
- `_collect_import_info()` — useful for analysis even with real module execution
- `_build_export_table()` — useful for validation

---

## 10. Mandatory Next Actions

1. **Tag 121 contaminated rows** in all merged_run.jsonl files with
   `assembly_recursion_artifact: true`. Recompute all metrics excluding these.

2. **Add recursion detector** to `CodeAssembler._assemble_multi_file()` before
   returning. Any function that calls itself via a renamed alias → REWRITE_ERROR.

3. **Add collision guard** to `_rewrite_imports_safe()` rename_map building.
   If `original_name` collides with an existing definition, skip the rename.

4. **Write the missing test**: alias import collides with local definition →
   assert assembly does NOT create recursion.

5. **Rerun gpt-5-mini on the 6 affected cases** (effect_order_b/c, retry_dup_b/c,
   partial_rollback_b/c) with the fix applied. Compare against contaminated data
   to quantify the measurement error.

6. **File a design issue** for replacing flattening with module-based execution
   as the canonical path. This is the real fix but requires more careful engineering.
