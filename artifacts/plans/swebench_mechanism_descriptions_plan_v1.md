# SWE-bench Mechanism Descriptions Plan v1

## Task
Write detailed causal mechanism descriptions for 10 SWE-bench bugs (first half batch).

## Scope
Output a JSON dict keyed by instance_id with oracle_ground_truth objects containing:
- mechanism_source
- mechanism_property
- mechanism_steps (3-5 steps)
- mechanism_outcome
- trap_description

## Files Touched
- Output: `analysis/swe_bench/swebench_oracle_mechanisms_batch1.json` (new file)

## Source Data Read
- `analysis/swe_bench/swebench_task_instances.json` (problem statements)
- `analysis/swe_bench/swebench_file_contents.json` (buggy source code)
- `analysis/swe_bench/swebench_reference_files.json` (oracle file list)
- `analysis/swe_bench/swebench_validation.md` (sections 7 and 9)

## 10 Bugs Analyzed
1. django__django-14315 - env={} vs env=None in runshell
2. sphinx-doc__sphinx-8551 - missing py:module on field xrefs
3. matplotlib__matplotlib-25479 - cmap.name vs registry name mismatch
4. django__django-16938 - select_related + only conflict in serializer
5. django__django-12741 - redundant 'using' parameter in execute_sql_flush
6. django__django-10554 - union queryset ordering mutates original query
7. mwaskom__seaborn-3187 - ScalarFormatter offset not applied to legend
8. pylint-dev__pylint-4604 - type comment Attribute nodes not stored
9. sphinx-doc__sphinx-8120 - locale dir ordering ignores user overrides
10. sympy__sympy-17318 - split_surds called with empty surds list

## Invariants
- Every mechanism chain verified against actual source code
- No guessing from problem statements alone
- Steps describe causation, not symptoms
