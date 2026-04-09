================================================================================
SWE-BENCH VALIDATION: DOES THE DDC DECOMPOSITION APPEAR IN REAL-WORLD TASKS?
================================================================================

## 1. Setup

- 20 SWE-bench Verified tasks (multi-file patches only, 2+ source files each)
- Model: gpt-5.4-mini
- 1 attempt per task, no retries, no hints
- Oracle source files provided in prompt (model sees the actual code)
- 8 repos: django, sphinx, matplotlib, sympy, pylint, seaborn, xarray, scikit-learn

## 2. Results

  Location accuracy:              20/20 = 100%
  Touched ALL reference files:     3/20 = 15%
  Exact fix match (line overlap): ~0/20 = 0%

The model touches at least one correct file in every case. But it almost
never produces code that matches the reference fix.

## 3. Key Finding

The DDC decomposition — location correct but execution wrong — appears
clearly on real-world SWE-bench tasks.

The model has 100% location accuracy (it knows WHERE the bug is) but
produces a DIFFERENT fix than the reference in every case. The model's
patches are in the right file, often in the right function, but implement
a different approach to solving the problem.

Additionally, on multi-file patches, the model typically fixes 1 of the
2 required files and misses the other. This mirrors the DDC pattern where
models fix at one node in the chain but don't propagate the fix through
all affected nodes.

## 4. Example Cases

### django__django-14315
  Reference files: base/client.py, postgresql/client.py (2 files)
  Model changed:   base/client.py (1 file)
  Model fix: Added `if env is not None` guard
  Reference fix: Changed `env` handling to merge with os.environ
  Verdict: RIGHT FILE, DIFFERENT FIX — model missed the second file entirely

### django__django-12741
  Reference files: commands/flush.py, base/operations.py (2 files)
  Model changed:   commands/flush.py, base/operations.py (2 files!)
  Model fix: Created execute_sql_flush with transaction.atomic wrapping
  Reference fix: Same structure — execute_sql_flush with transaction.atomic
  Verdict: CLOSEST MATCH — 2/6 reference lines overlap, same approach

### sympy__sympy-17318
  Reference files: radsimp.py, sqrtdenest.py (2 files)
  Model changed:   radsimp.py, sqrtdenest.py (2 files!)
  Model fix: Added sorting and empty-check for surds
  Reference fix: Changed split_surds to handle rational square arguments
  Verdict: BOTH FILES TOUCHED, DIFFERENT APPROACH

### matplotlib__matplotlib-25479
  Reference files: cm.py, colors.py (2 files)
  Model changed:   cm.py (1 file)
  Model fix: Added comments about registry name vs colormap name
  Reference fix: Added code to update colormap.name to match registry name
  Verdict: RIGHT FILE, INCOMPLETE — model added comments instead of code

### sphinx-doc__sphinx-8548
  Reference files: autodoc/__init__.py, autodoc/importer.py (2 files)
  Model changed:   autodoc/__init__.py, autodoc/importer.py (2 files!)
  Model fix: Added MRO-based docstring lookup for inherited members
  Reference fix: Added get_class_members with ClassAttribute handling
  Verdict: BOTH FILES, DIFFERENT IMPLEMENTATION — 4/27 lines overlap

## 5. Multi-File Coverage

Of the 20 tasks (all requiring 2+ file changes):
  - Model touched ALL reference files:  3/20 (15%)
  - Model touched SOME reference files: 17/20 (85%)
  - Model touched NO reference files:   0/20 (0%)

When the model missed files, it typically fixed the "main" file
but missed the "supporting" file — the same depth pattern as DDC
where models fix the node where the symptom appears but miss the
node where the corruption originates.

## 6. Conclusion

## 6. Docker Evaluation Results (SWE-bench harness)

Patches were generated using full-file replacement (model outputs entire
fixed file, diff computed programmatically). This eliminates patch format
errors — all non-empty patches apply cleanly.

  Total tasks:         20
  Patches applied:     20/20 (100%)
  Tests resolved:       2/20 (django-12741, sphinx-8120)
  Tests failed:        18/20 (patch applied, tests ran, fix was wrong)
  Errors:               0/20

  Location accuracy:              19/20 = 95%
  Execution pass rate:             2/20 = 10%
  Execution | location correct:    2/19 = 11%

## 7. Per-Case Test Failure Analysis

Every failure is a genuine implementation error — patch applied cleanly,
tests ran, but the code logic was wrong:

  django-14315:        Returns {} instead of None for empty env — wrong
                       semantics. Expected (args, None), got (args, {}).
                       3 test assertions failed.

  django-16938:        Used values_list("pk", flat=True) instead of
                       select_related().only("pk") — causes FieldError
                       on traversed fields. 11 errors.

  matplotlib-25479:    Fixed cm.py but missed colors.py — colormap name
                       not updated after registration. 4 tests failed.

  sphinx-8551:         Missing py:module attribute on xref nodes —
                       incomplete fix in docfields.py. 1 test failed.

  seaborn-3187:        Legend offset not disabled — ScalarFormatter still
                       applies offset. assert 2.5 > 1e7. 2 tests failed.

  pylint-4604:         Added IS_PYPY import from constants.py but didn't
                       define the constant there. ImportError on test load.

  pylint-4661:         Used appdirs module for XDG directory handling but
                       the module isn't installed in the test environment.
                       ModuleNotFoundError.

  sphinx-7462:         Broke tuple unpacking in AST unparse — AttributeError
                       and SyntaxError on empty tuple parsing. 4 tests failed.

  sphinx-8120:         i18n translation locale directory handling wrong —
                       meta tags and label targets not translated. 4 tests.

  sympy-17318:         _sqrt_match logic wrong for complex input —
                       assert _sqrt_match(4 + I) == [] fails.

  sympy-19783:         Infinite recursion in __mul__ for IdentityOperator —
                       RecursionError on Dagger(A*B). Model created a cycle.

  sympy-22080:         IndentationError — model produced syntactically
                       invalid Python in the codeprinter module.

Failure mode breakdown:
  Wrong logic / incomplete fix:   8  (right approach, wrong details)
  Missing second file:            1  (matplotlib — only changed 1 of 2)
  Missing dependency:             2  (pylint — referenced undefined symbols)
  Syntax / recursion error:       3  (broken code structure)

## 8. Resolved Cases

django-12741:  Model correctly created execute_sql_flush method with
               transaction.atomic wrapping in base/operations.py AND
               updated flush command to call it. Both reference files
               touched. Same approach as reference fix.

sphinx-8120:   Model correctly modified application.py to fix locale
               directory initialization order. Fix in one file was
               sufficient to pass tests.

## 9. V5: Context-File Rerun (Non-Circular Location Accuracy)

V4 gave only oracle files — model had to fix the 2 files it was shown, so
100% location accuracy was circular. V5 gives oracle + import-linked context
files (3–10 files per task). Model must choose which files to edit.

  Total tasks:                      20
  Patches applied:                  19/19 (100%) + 1 empty (scikit-learn-25102)
  Tests resolved:                    2/20 (django-12741, sphinx-8120)
  Tests failed:                     17/19
  Errors:                            0

  Location accuracy (any oracle):   18/20 = 90%
  All oracle files hit:              5/20 = 25%
  Execution pass rate:               2/20 = 10%
  Execution | location correct:      2/18 = 11%

### V4 → V5 Comparison

  Metric                      V4 (oracle-only)    V5 (context files)
  Location (any oracle)       19/20 = 95%         18/20 = 90%
  All oracle files hit         3/20 = 15%          5/20 = 25%
  Tests resolved               2/20 = 10%          2/20 = 10%
  Errors                       0/20                0/20

Location dropped only 5 points (95→90%) when file set tripled.
Multi-file coverage improved (15→25%) — context helps identify related files.
Execution accuracy unchanged — adding more files didn't help or hurt.

### V5 Location Results Per Task

  ALL (5/20): django-14315, django-12741, django-10554, sympy-17318, pylint-6528
  HIT (13/20): sphinx-8551, matplotlib-25479, django-16938, seaborn-3187,
               pylint-4604, sphinx-8120, sympy-22080, sphinx-7462,
               pylint-4661, xarray-3305, sphinx-8548, matplotlib-24870,
               xarray-6938
  MISS (2/20): sympy-19783 (edited complexes.py instead of dagger.py),
               scikit-learn-25102 (empty patch)

### V5 Per-Case Failure Analysis

  Category breakdown (17 failed):
    WRONG_LOGIC:  11  (patch applied, tests ran, fix was incorrect)
    IMPORT_ERROR:  3  (referenced undefined/removed symbols)
    MISSING_FILE:  2  (incomplete: missing dependency or second file)

  django-10554:   IMPORT_ERROR — removed get_order_dir import. 2 tests failed.
  django-14315:   WRONG_LOGIC — env parameter mismatch. 2 tests failed.
  django-16938:   WRONG_LOGIC — FieldError on deferred+select_related. 1 test.
  matplotlib-24870: MISSING_FILE — undefined docstring key causes KeyError. 1 error.
  matplotlib-25479: WRONG_LOGIC — colormap equality checks broken. 4 tests.
  seaborn-3187:   WRONG_LOGIC — legend text "1 +1e8" instead of float. 2 tests.
  xarray-3305:    WRONG_LOGIC — quantile() returns empty attrs dict. 1 test.
  xarray-6938:    WRONG_LOGIC — to_index_variable_copy assertion failed. 1 test.
  pylint-4604:    IMPORT_ERROR — IS_PYPY not in pylint.constants. All tests.
  pylint-4661:    MISSING_FILE — appdirs module not found. All tests.
  pylint-6528:    WRONG_LOGIC — recursive ignore not applied. 4 tests.
  sphinx-7462:    WRONG_LOGIC — AttributeError in signature parsing. 3 tests.
  sphinx-8548:    WRONG_LOGIC — inherited attribute order changed. 1 test.
  sphinx-8551:    WRONG_LOGIC — missing py:module on xref nodes. 1 test.
  sympy-17318:    WRONG_LOGIC — _sqrt_match returns wrong result. 1 test.
  sympy-19783:    IMPORT_ERROR — can't import polar_lift from wrong file. All.
  sympy-22080:    WRONG_LOGIC — NameError: AssocOpDispatcher not defined. 3 tests.

## 10. Conclusion

The mechanism → location → implementation decomposition observed on DDC
synthetic cases appears clearly on real-world SWE-bench Verified tasks:

  - Location accuracy is high: 90% of patches touch the correct file
    (measured non-circularly with 3–10 candidate files per task)
  - Execution accuracy is low: only 10% of patches pass tests
  - The gap is NOT caused by patch format issues (0 errors with full-file replacement)
  - Every failure is a genuine code quality issue: wrong logic, missing dependencies,
    incomplete multi-file fixes, or broken syntax
  - Adding context files barely affected location (95→90%) or execution (10%→10%)

The 90% → 10% drop from location to execution mirrors the DDC finding where
models consistently identify the right intervention point but fail to implement
correct fixes. On DDC cases this manifests as depth confusion; on SWE-bench it
manifests as logic errors, missing cross-file propagation, and dependency issues.
The underlying pattern is the same: knowing WHERE is easier than knowing HOW.
