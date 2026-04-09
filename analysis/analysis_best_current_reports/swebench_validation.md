================================================================================
SWE-BENCH VALIDATION: THE REASONING-EXECUTION GAP ON REAL-WORLD BUGS
================================================================================

## 1. Setup

- 31 SWE-bench Verified tasks (multi-file patches only, 2+ source files each)
- Model: gpt-5.4-mini
- 1 attempt per task, no retries
- Full-file replacement: model outputs entire fixed file, diff computed
  programmatically (eliminates patch format errors)
- Oracle files provided in prompt (model sees the buggy source code)
- 10 repos: django, sphinx, matplotlib, sympy, pylint, seaborn, xarray,
  scikit-learn, astropy, pytest
- Oracle evaluation: oracle_reasoning_truth_enriched prompt, partial_mode=strict,
  against hand-verified mechanism descriptions
- Execution truth: SWE-bench Docker harness (actual test suite execution)

## 2. Results

  Total cases:                  31
  Execution pass:                2/31 =  6.5%
  Oracle correct (mechanism):   22/31 = 71.0%
  Exec | oracle correct:         2/22 =  9.1%

## 3. Decomposition

  Category           Count   Pct
  ─────────────────────────────────
  SUCCESS               2     6%   oracle correct + tests pass
  LEG                  19    61%   oracle correct + tests fail
  WRONG MECHANISM       9    29%   oracle wrong + tests fail
  LUCKY FIX             1     3%   oracle wrong + tests pass

The Reasoning-Execution Gap (LEG) is the dominant failure mode at 61%.

## 4. Resolved Cases (2)

django__django-12155:
  Bug: trim_docstring miscalculates indentation when first line has text.
  Model correctly replaced custom trim_docstring with inspect.cleandoc.
  1/1 tests pass.

django__django-12741:
  Bug: execute_sql_flush takes redundant `using` parameter.
  Model correctly simplified signature and updated flush command caller.
  2/2 tests pass.

## 5. Lucky Fix (1)

sphinx-doc__sphinx-8120:
  Oracle judged mechanism WRONG (model described path mismatch, real bug is
  initialization ordering), but the generated code happened to pass tests.
  1/1 tests pass.

## 6. LEG Cases: Per-Case Mismatch Analysis (19)

Each LEG case has correct reasoning (oracle_correct=true) but failed
execution. Below is the specific mismatch between understanding and code.

### django__django-14315 (9/11 tests pass)
  Bug: `if env:` falsey for empty dict, stripping subprocess environment.
  Model's fix: Changed `if env:` to `if env is not None:` and rewrote
  postgresql to return None instead of {}. Correct concept.
  Mismatch: Test expects `subprocess.run(env=None)` for empty env, but
  model's approach merges os.environ unconditionally when env is not None,
  producing `env={...all vars...}` instead of `env=None`.
  Gap type: Subtle semantic edge case — correct for the reported bug but
  violates a different test expectation about empty-dict passthrough.

### django__django-16938 (18/23 tests pass)
  Bug: .only('pk') conflicts with custom manager's select_related.
  Model's fix: Removed .only("pk") from python.py serializer.
  Mismatch: Identical bug exists in xml_serializer.py — model fixed only
  one of two serializers. 5 XML serializer tests still fail.
  Gap type: Missing multi-file propagation.

### django__django-14170 (2/2 F2P pass, 9 P2P regressions)
  Bug: __iso_year uses calendar year bounds instead of ISO year bounds.
  Model's fix: Added `self.lookup_name == 'year'` guard to skip optimization.
  Mismatch: Guard disables the BETWEEN optimization for ALL non-year lookups
  including regular year extract, breaking 9 existing year-related tests.
  Gap type: Overly broad guard causes collateral regressions.

### django__django-13195 (1/5 tests pass)
  Bug: delete_cookie() doesn't preserve SameSite attribute.
  Model's fix: Added samesite parameter to delete_cookie in response.py.
  Mismatch: Session middleware and cookie storage callers also need to pass
  samesite through. Model fixed the API but not the call sites.
  Gap type: Missing multi-file propagation.

### django__django-13512 (1/3 tests pass)
  Bug: JSONField admin display uses ensure_ascii=True, escaping unicode.
  Model's fix: Changed forms/fields.py JSONField.prepare_value.
  Mismatch: The admin display path goes through admin/utils.py
  display_for_field, not forms/fields.py. Model fixed the wrong call site.
  Gap type: Wrong file — correct diagnosis, wrong intervention point.

### sphinx-doc__sphinx-7462 (1/2 tests pass)
  Bug: unparse() has no handler for empty ast.Tuple, causing IndexError.
  Model's fix: Added `if node.elts: result.pop()` guard in python.py.
  Mismatch: The fix is in sphinx/domains/python.py but the test also expects
  a fix in sphinx/pycode/ast.py which has the same unguarded pop().
  Gap type: Missing second file with identical bug.

### django__django-12406 (0/3 tests pass)
  Bug: RadioSelect shows blank option when blank=False on model field.
  Model's fix: Changed forms/models.py and related.py.
  Mismatch: Model reformatted docstrings but didn't add the blank=False
  check to ModelChoiceField.__init__ or ForeignKey.formfield.
  Gap type: Cosmetic patch — no functional change despite touching right files.

### django__django-13121 (0/1 tests pass)
  Bug: DurationField+DurationField arithmetic fails on SQLite/MySQL.
  Model's fix: Changed base/operations.py.
  Mismatch: Only reformatted docstrings in operations.py. No changes to
  combine_duration_expression or expressions.py.
  Gap type: Cosmetic patch — no functional change.

### django__django-11734 (0/1 tests pass, 275 regressions)
  Bug: OuterRef in exclude() resolves against wrong model.
  Model's fix: Changed query.py.
  Mismatch: Produced a large patch (71K) that modified many query methods
  but introduced 275 test regressions. The split_exclude fix was buried
  in destructive changes to unrelated query internals.
  Gap type: Destructive over-editing.

### django__django-10554 (0/2 tests pass, 23 regressions)
  Bug: Union queryset ORDER BY references stale aliases after change_aliases.
  Model's fix: Empty patch (no files changed in output).
  Mismatch: Model produced no code despite understanding the alias issue.
  23 regressions from the v5 run's context-file approach.
  Gap type: Empty patch.

### pylint-dev__pylint-6528 (0/4 tests pass)
  Bug: --recursive=y doesn't apply ignore patterns to discovered subfiles.
  Model's fix: Added _is_ignored helper function in expand_modules.py.
  Mismatch: Wrote the helper but didn't wire it into the recursive file
  discovery loop. The function exists but is never called during recursion.
  Gap type: Helper written but not integrated.

### pylint-dev__pylint-8898 (0/1 tests pass, 18 regressions)
  Bug: bad-names-rgxs splits regex patterns on commas inside quantifiers.
  Model's fix: Changed utils.py and argument.py with new splitting logic.
  Mismatch: New splitting function handles escaped commas but still splits
  on commas inside curly-brace quantifiers like {1,2}.
  Gap type: Incomplete fix — addressed part of the problem.

### pylint-dev__pylint-4604 (0/21 tests pass)
  Bug: Unused-import false positive for imports used in type comments.
  Model's fix: Empty patch (no files changed).
  Mismatch: No code produced despite understanding the type comment scanning gap.
  Gap type: Empty patch.

### pylint-dev__pylint-4661 (0/1 tests pass)
  Bug: ~/.pylint.d instead of XDG-compliant path (standards request, but
  in SWE-bench Verified so has a test).
  Model's fix: Empty patch.
  Mismatch: No code produced.
  Gap type: Empty patch.

### scikit-learn__scikit-learn-25102 (0/2 tests pass)
  Bug: Feature selectors lose DataFrame dtypes through numpy conversion.
  Model's fix: Changed sklearn/base.py — rewrote __repr__ method.
  Mismatch: Deleted the __repr__ method and replaced it with a stub, but
  didn't modify SelectorMixin._transform in feature_selection/_base.py
  where the actual dtype erasure occurs.
  Gap type: Wrong file — destructive edit to unrelated code.

### matplotlib__matplotlib-24870 (0/1 tests pass, 65 regressions)
  Bug: contour() produces degenerate 7 identical levels for boolean input.
  Model's fix: Empty patch (v5 context-file run).
  Mismatch: No code produced. 65 regressions from unrelated context changes.
  Gap type: Empty patch.

### pydata__xarray-6938 (0/1 tests pass)
  Bug: swap_dims mutates original Dataset via shared Variable references.
  Model's fix: Empty patch (v5 context-file run).
  Mismatch: No code produced.
  Gap type: Empty patch.

### sphinx-doc__sphinx-8548 (0/1 tests pass)
  Bug: autodoc :inherited-members: misses inherited data attributes.
  Model's fix: Empty patch (v5 context-file run).
  Mismatch: No code produced.
  Gap type: Empty patch.

### sympy__sympy-19783 (0/2 tests pass, 9 regressions)
  Bug: Dagger(A) * IdentityOperator() not simplified because Dagger lacks __mul__.
  Model's fix: Empty patch (baseline), 1 file on retry.
  Mismatch: No code produced on baseline despite understanding the MRO issue.
  Gap type: Empty patch.

## 7. LEG Failure Mode Taxonomy

  Empty patch (7/19 = 37%):
    Model understands the bug but produces no code changes at all.
    Cases: django-10554, pylint-4604, pylint-4661, matplotlib-24870,
    xarray-6938, sphinx-8548, sympy-19783.

  Missing multi-file propagation (3/19 = 16%):
    Model fixes one file correctly but misses the identical bug or
    required call-site update in a second file.
    Cases: django-16938, django-13195, sphinx-7462.

  Cosmetic-only patch (2/19 = 11%):
    Model touches the right files but only reformats comments/docstrings
    without making any functional changes.
    Cases: django-12406, django-13121.

  Wrong file / wrong call site (2/19 = 11%):
    Model makes a real functional change but in the wrong file, missing
    the actual code path where the bug manifests.
    Cases: django-13512, scikit-learn-25102.

  Subtle semantic error (2/19 = 11%):
    Model's fix is 80-90% correct but has a subtle semantic mismatch
    that fails specific test expectations.
    Cases: django-14315 (9/11 pass), django-14170 (2/2 F2P pass but regressions).

  Destructive over-editing (2/19 = 11%):
    Model makes large-scale changes that break many unrelated tests.
    Cases: django-11734 (275 regressions), pylint-8898 (18 regressions).

  Helper not integrated (1/19 = 5%):
    Model writes the correct helper function but doesn't call it.
    Cases: pylint-6528.

## 8. Test-Level Analysis

Across the 19 LEG cases, the model partially solves many bugs:

  Total FAIL_TO_PASS tests:     84
  Tests passing on baseline:    32 (38%)
  Tests still failing:          52 (62%)
  P2P regressions:             381 (across 6 cases)

Notable near-misses:
  django-14315:  9/11 tests pass (82%) — 2 edge case tests remain
  django-16938: 18/23 tests pass (78%) — XML serializer not updated
  django-14170:  2/2 F2P pass (100%) — but 9 regressions block resolution

## 9. Conclusion

The Reasoning-Execution Gap accounts for 61% of failures on real-world
multi-file SWE-bench bugs. The model correctly identifies the root cause
mechanism in 71% of cases, but converts correct understanding to working
code only 9.1% of the time.

The gap is NOT a binary phenomenon — 38% of individual tests pass even
in LEG cases, and some cases are within 2-3 tests of full resolution.
The dominant failure modes are:

  1. Empty patches (37%) — model can't translate reasoning to code at all
  2. Multi-file propagation failures (16%) — fixes one file, misses another
  3. Wrong intervention point (11%) — correct diagnosis, wrong code location
  4. Cosmetic patches (11%) — touches right files, makes no functional change

The pattern is consistent across Django, Sphinx, SymPy, pylint, and
scikit-learn. Knowing WHERE the bug is and WHY it occurs does not
reliably translate to knowing HOW to write the fix.
