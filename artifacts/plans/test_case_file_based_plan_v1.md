# Plan: Migrate test_case.py to file-based module loading

## Problem

`scripts/test_case.py` concatenates all code files into a single string, strips cross-file imports with a regex hack (`strip_local_imports`), and `exec`s the result. This breaks for cases with absolute dotted imports (e.g. `from case_data.code_snippets_v2.l3_state_pipeline.pipeline import ...`) because the stripping logic only matches simple `from X import` where X is a bare sibling name.

Two cases fail: `l3_state_pipeline` and `commit_gate`.

The canonical evaluation pipeline (`exec_canonical.py` + `run_case.py`) already solves this correctly: files are written to disk, imported via `importlib`, and merged into a single namespace. The manual test tool should use the same approach.

## Scope

**One file changed:** `scripts/test_case.py`

- Delete: `get_sibling_names`, `strip_local_imports` (dead code after change)
- Rewrite: `load_module` to use temp dir + importlib instead of concatenation + exec

## Design

New `load_module(file_paths, extra_fix=None)`:

1. Create a temp directory
2. Write an `__init__.py` into it
3. Copy each file from `file_paths` into the temp dir (basename only)
4. If `extra_fix` is provided, copy it too (imported last → its definitions override)
5. Add temp dir to `sys.path`
6. Import each module via `importlib.import_module(stem)`
7. Build merged namespace: iterate modules in order, last writer wins (same as `run_case.py`). Copy all non-dunder attributes into a `types.ModuleType`.
8. Clean up: remove temp dir from `sys.path`, delete imported modules from `sys.modules`, delete temp dir
9. Return the merged module

Import order: code files first (sorted by basename, matching `run_case.py`), then extra_fix last. This ensures the fix's definitions override the originals.

## Why not subprocess?

The canonical pipeline uses subprocess for isolation. The manual test tool doesn't need that — in-process import + merge is faster and simpler for interactive use. The key fix is using real Python imports instead of the concatenation hack.

## Invariants

- `test_case.py --all --ref` must produce 58/58 PASS (or ERROR only for legitimate issues)
- `l3_state_pipeline` and `commit_gate` ref fixes must PASS
- No new dependencies
- No changes to any other file

## Risks

- Module cache pollution: mitigated by removing entries from `sys.modules` after each run
- Temp dir cleanup on exception: mitigated by using `try/finally`
