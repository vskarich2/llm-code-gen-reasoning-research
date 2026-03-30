# Concatenation vs Module Execution — Design Analysis

**Date:** 2026-03-30

---

## A. Comparison Table

| Dimension | Concatenation + Rewriting | Real Module Execution |
|---|---|---|
| **Semantic fidelity** | LOW — flattens all files into one namespace, loses module boundaries | HIGH — standard Python import semantics |
| **`from X import Y`** | Delete import, Y available from concat | Works natively |
| **`from X import Y as Z`** | Delete + AST rename Z→Y (complex) | Works natively |
| **`import X; X.func()`** | Delete + synthesize SimpleNamespace (complex) | Works natively |
| **Module-level state** | All state shared in one namespace, collision risk | Each module has its own namespace |
| **Circular imports** | N/A (no imports) — but name ordering matters | Fails on `from X import Y` circular patterns. Needs 2-pass loading. |
| **Determinism** | YES — same input → same AST transform → same output | YES if sys.modules cleaned between cases |
| **State isolation** | Natural — single exec scope, fresh each time | Requires explicit sys.modules cleanup |
| **Dynamic access** | Cannot resolve `getattr(X, ...)` — keeps import, fails at runtime | Works natively |
| **Engineering complexity** | HIGH — 828 lines of AST analysis, rewriting, namespace synthesis | LOW — ~50 lines of module loading + retry |
| **Error classification** | Infrastructure errors (assembly bugs) confused with model errors | Clean separation — import errors are real |
| **Override semantics** | Last-definition-wins via concat ordering | Model module replaces original in sys.modules |
| **Extra files** | Silently dropped | Can be loaded as additional modules |

---

## B. Failure Mode Matrix

| Failure Type | Concatenation | Module Execution |
|---|---|---|
| Alias import (`as Z`) breaks | FIXED (AST rename) | N/A (native) |
| Module-qualified (`X.func()`) breaks | FIXED (SimpleNamespace) | N/A (native) |
| Name collision (two modules define `reset`) | Detected → REWRITE_ERROR | Each module has own namespace → no collision |
| Dynamic access (`getattr`) | Import kept → ModuleNotFoundError | Works natively |
| Module shadowing (`X = something`) | Detected → REWRITE_ERROR | Works natively (assignment scoped to module) |
| Circular imports | N/A | Fails on `from X import Y` circular. Fixed with 2-pass loading. |
| Load ordering | N/A (all in one scope) | Requires dependency ordering. Fixed with retry. |
| State leakage between cases | None (fresh exec each time) | sys.modules must be cleaned between cases |
| Module-level side effects | Execute in concat order | Execute in load order — may differ |
| Star imports (`from X import *`) | Removed (safe in concat) | Works but pollutes namespace |
| Relative imports | Removed | Need package structure or special handling |

---

## C. Key Tradeoffs

### Concatenation optimizes for:
- **Simplicity of execution** — one compile, one exec, one namespace
- **State isolation** — fresh dict each time, no cleanup needed
- **No import infrastructure** — no sys.modules, no loaders, no paths

### Concatenation sacrifices:
- **Semantic fidelity** — Python code doesn't normally run in a single flattened namespace
- **Engineering simplicity** — the AST rewriting to simulate module semantics is 828 lines of complex code
- **Correctness** — 47 evaluations failed due to assembly bugs in the original implementation; even after fixes, edge cases remain (dynamic access, circular references within concat scope)

### Module execution optimizes for:
- **Semantic fidelity** — real Python modules with real imports
- **Engineering simplicity** — ~50 lines instead of 828
- **Zero rewriting** — no AST transforms, no namespace synthesis, no alias handling
- **Future-proofing** — any import pattern works, no new edge cases to handle

### Module execution sacrifices:
- **State isolation** — must clean sys.modules between cases (trivial but required)
- **Load ordering** — must handle dependency order (solved with 2-pass retry)

---

## D. Recommendation

**HYBRID: Module execution as primary, concatenation as fallback.**

### Rationale:

1. **Module execution handles 39/39 multi-file cases with 2-pass loading.** Every benchmark case works. No AST rewriting needed.

2. **Concatenation has proven its failure modes.** 47 infrastructure-induced failures across ablation runs. The AST rewriting fixes are correct but add 828 lines of complexity that will need ongoing maintenance as LLMs produce new import patterns.

3. **Module execution eliminates the entire class of assembly bugs.** No alias rewriting, no namespace synthesis, no collision detection, no dynamic access detection. These all become non-issues.

4. **State leakage is trivially preventable.** Clean sys.modules before each case. This is ~3 lines of code.

5. **The override model maps naturally.** Model code replaces the target module in sys.modules. Original modules stay. No concat ordering or last-definition-wins semantics needed.

### Why hybrid, not pure module:

- Single-file cases don't need module infrastructure. Concat is simpler and correct for them.
- If a model produces code that doesn't work as a real module (e.g., code that assumes it's been concatenated), fallback to concat mode prevents false failures.
- The existing test infrastructure uses concat-style exec in many places. A gradual migration is safer.

### Implementation:

```python
class CodeAssembler:
    def assemble(self, model_code, case):
        if single_file(case):
            return self._single_file(model_code)

        # Try module execution first
        result = self._try_module_execution(model_code, case)
        if result.status == "SUCCESS":
            return result

        # Fallback to concat
        return self._concat_assembly(model_code, case)
```

---

## E. Migration Plan

### Phase 0: Add module execution alongside concat (no behavior change)
1. Implement `_try_module_execution()` in CodeAssembler
2. Run both paths on every case, compare results
3. Log discrepancies
4. Default to concat (current behavior)

### Phase 1: Module execution as primary
1. Switch default to module execution
2. Fallback to concat on failure
3. Log all fallbacks
4. Run full ablation, compare metrics

### Phase 2: Remove concat for multi-file
1. If Phase 1 shows zero fallbacks, remove concat path for multi-file cases
2. Keep concat for single-file cases (simpler, no module overhead)
3. Delete AST rewriting code (~600 lines)

### Phase 3: Simplify
1. Remove `_rewrite_imports_safe`, `_resolve_qualified_imports`, `_build_export_table`, `_detect_dynamic_access`, `_detect_shadowing`, `_NameRewriter`, `_ImportRemover`
2. CodeAssembler becomes ~100 lines
3. Test suite shrinks accordingly

### Risk mitigation:
- Phase 0 is zero-risk (parallel execution, no behavior change)
- Phase 1 has fallback (concat catches any module execution failures)
- Phase 2 only happens after empirical proof from Phase 1

---

## F. Empirical Evidence

### Test results from this analysis:

| Approach | Multi-file cases | Success rate | Lines of code |
|---|---|---|---|
| Concatenation (current) | 39 | 39/39 after 828 lines of AST fixes | 828 |
| Module execution (naive, single pass) | 39 | 25/39 (14 ImportError) | ~30 |
| Module execution (2-pass retry) | 39 | 39/39 | ~50 |

### State leakage test:
- Confirmed: modules persist in sys.modules across cases if not cleaned
- Fix: 3 lines of cleanup code
- No cases share module names across different case families, so leakage between consecutive test runs of the SAME case is the only risk (handled by cleanup)

### Circular import test:
- `from X import Y` circular: fails on first pass
- Fixable with 2-pass loading (both modules get exec'd, then imports resolve)
- No benchmark cases currently have circular imports
