# SWE-bench Mechanism Descriptions Plan v2

## Changes from v1
- v1 covered first batch of 10 bugs; this covers second batch of 10 bugs
- Output file named batch2 instead of batch1

## Task
Write detailed causal mechanism descriptions for 10 SWE-bench bugs (second half batch).

## Scope
Output a JSON dict keyed by instance_id with oracle_ground_truth objects containing:
- mechanism_source
- mechanism_property
- mechanism_steps (3-5 steps)
- mechanism_outcome
- trap_description

## Files Touched
- Output: `analysis/swe_bench/swebench_oracle_mechanisms_batch2.json` (new file)

## Source Data Read
- `analysis/swe_bench/swebench_task_instances.json` (problem statements)
- `analysis/swe_bench/swebench_file_contents.json` (buggy source code)
- `analysis/swe_bench/swebench_reference_files.json` (oracle file list)
- `analysis/swe_bench/swebench_validation.md` (sections 7 and 9)

## 10 Bugs Analyzed
1. sympy__sympy-19783 - Dagger * IdentityOperator not simplified
2. sympy__sympy-22080 - Mod function lambdify precedence bug
3. sphinx-doc__sphinx-7462 - IndexError on empty tuple annotation
4. pylint-dev__pylint-4661 - XDG Base Directory compliance for PYLINTHOME
5. pydata__xarray-3305 - DataArray.quantile ignores keep_attrs
6. pylint-dev__pylint-6528 - recursive mode ignores ignore settings
7. sphinx-doc__sphinx-8548 - autodoc inherited-members misses data attributes
8. matplotlib__matplotlib-24870 - contour doesn't auto-detect bool arrays
9. pydata__xarray-6938 - swap_dims mutates original object
10. scikit-learn__scikit-learn-25102 - feature selection loses DataFrame dtypes

## Invariants
- Every mechanism chain verified against actual source code
- No guessing from problem statements alone
- Steps describe causation, not symptoms
