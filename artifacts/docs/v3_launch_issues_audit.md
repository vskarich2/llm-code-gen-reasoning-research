# V3 Ablation Launch Issues Audit

**Date:** 2026-04-03
**Context:** Attempting to launch the v3 prompt family ablation (1,740 work items, 2 models, 5 conditions, 58 cases, 3 trials)

---

## Issues Encountered (chronological)

### Issue 1: `validate_prompts` not in config allow-list

**Symptom:** All 1,740 workers immediately failed with exit code 1.
**Error:** `ValueError: Unknown fields in execution config: {'validate_prompts'}`
**Root cause:** `experiment_config.py` has a `_KNOWN_EXEC_FIELDS` allow-list that rejects unknown YAML keys. We added `validate_prompts` to the `ExecutionConfig` dataclass and its parsing, but forgot to add it to the allow-list.
**Fix applied:** Added `"validate_prompts"` to `_KNOWN_EXEC_FIELDS`.
**Time lost:** ~2 minutes (full 1,740-worker launch, immediate failure).
**Prevention:** The allow-list pattern is brittle — adding a config field requires touching 3 places (dataclass, parser, allow-list). Should be derived from the dataclass automatically.

### Issue 2: Classifier metadata missing grounded-mode variables

**Symptom:** `PromptMetadataDriftError` — template references `ground_truth_failure_mode` etc. but metadata doesn't declare them.
**Error:** `Template 'classify_reasoning_v3' references undeclared variables: ['ground_truth_failure_mode', 'ground_truth_invariant', 'ground_truth_trap']`
**Root cause:** The v3 classifier metadata `conditional_groups` listed the grounded variables but `input_types` didn't include them. The v2 metadata had them in both places — we didn't copy the pattern exactly.
**Fix applied:** Added `ground_truth_*` to `input_types` in metadata.
**Caught by:** The `validate_prompts=True` AST checker — this is exactly why we turned validation on.
**Prevention:** Template metadata should be auto-generated from template AST, not hand-maintained.

### Issue 3: Metadata declares `risk_check` but template doesn't use it

**Symptom:** `PromptMetadataDriftError`
**Error:** `Metadata for 'classify_reasoning_v3' declares variables not referenced in template: ['risk_check']`
**Root cause:** Copy-paste from v2 metadata. The v3 classifier doesn't use `risk_check` (intentionally removed) but we left it in `optional_inputs`.
**Fix applied:** Removed `risk_check` from v3 classifier metadata.
**Caught by:** `validate_prompts=True` AST checker.
**Prevention:** Same as Issue 2.

### Issue 4: `run_case.py` missing `import os`

**Symptom:** ALL cases across ALL conditions fail with `NAME_ERROR: name 'os' is not defined`.
**Error:** `NameError: name 'os' is not defined` in `run_case.py:153`
**Root cause:** When we added `case_data_dir = os.path.join(project_root, "case_data")` to `run_case.py` for test discovery, we used `os.path.join` but never added `import os` to the file's imports.
**Fix applied:** Added `import os` to `run_case.py`.
**Time lost:** ~5 minutes. This caused a full 1,740-worker run to produce 0% pass rate across every condition and model, appearing as if the entire v3 prompt family was broken. Required investigation to realize it was an infrastructure bug, not a prompt issue.
**Prevention:** Any code change to `run_case.py` must be tested with a 1-case end-to-end smoke test before launching an ablation. The preflight check did NOT catch this because it uses a different code path (file-based `importlib.util.spec_from_file_location` in `test_loader.py` vs module-based `importlib.import_module` in `run_case.py`).

### Issue 5: `cases_v2.json` file paths include `case_data/` prefix

**Symptom:** Model outputs file keys like `case_data/code_snippets_v2/alias_config_a/config.py` because that's what's in the prompt. Reconstruction succeeds (it just uses the keys as-is) but the paths don't match what the test harness expects.
**Error:** Not a crash — tests run but model code references files by the wrong path.
**Root cause:** During the earlier file reorg, we updated `cases_v2.json` code_files paths from `code_snippets_v2/...` to `case_data/code_snippets_v2/...` so `runner.py` could find them. But the model then echoes these full paths back as file keys. We reverted the paths and instead fixed `runner.py` to resolve them via `BASE_DIR / "case_data" / rel_path`.
**Fix applied:** Reverted `cases_v2.json` paths to `code_snippets_v2/...`. Updated `runner.py:49` to prepend `case_data/` when loading files.
**Prevention:** File paths in `cases_v2.json` are part of the prompt contract — they become file keys in the model's JSON output. Changing them changes the prompt. This should have been caught in the file reorg audit.

### Issue 6: Preflight and execution use different test discovery paths

**Symptom:** Preflight passes but execution fails with "No test found".
**Detail:**
- Preflight (`test_loader.py`): Uses `TESTS_V2_DIR` from `core.config.paths` → resolves to `case_data/tests_v2/`. Loads via `importlib.util.spec_from_file_location(path)` — file-based.
- Execution (`run_case.py`): Uses `importlib.import_module("tests_v2.test_{family}")` — module-based. Requires `tests_v2/` on `sys.path` or `PYTHONPATH`.
**Root cause:** Two different test discovery mechanisms that were never unified. The file reorg moved `tests_v2/` to `case_data/tests_v2/`. The file-based path survived (it uses an explicit config path). The module-based path broke (it relies on `sys.path`).
**Fix applied:** Added `case_data/` to both `PYTHONPATH` in `exec_canonical.py` and `sys.path` in `run_case.py`.
**Prevention:** Preflight must use the SAME test discovery mechanism as execution. Currently they diverge — preflight uses file-based loading, execution uses module imports. This should be unified.

### Issue 7: Manifest file race condition at high worker count

**Symptom:** Orchestrator crash with `FileNotFoundError: manifest.tmp -> manifest.json`
**Error:** `FileNotFoundError: [Errno 2] No such file or directory: 'logs/v3_full_ablation/manifest.tmp' -> 'logs/v3_full_ablation/manifest.json'`
**Root cause:** `rm -rf logs/v3_full_ablation` removed the run directory, then the orchestrator tried to write the manifest to a directory that no longer exists. The `atomic_write_json` function writes to a `.tmp` file then `os.replace`s it — both require the parent directory to exist.
**Fix applied:** `mkdir -p logs/v3_full_ablation` before relaunch. Also reduced workers from 300 to 100 to reduce concurrent filesystem pressure.
**Prevention:** The orchestrator should create the run directory if it doesn't exist before writing the manifest. Or: don't `rm -rf` the run dir between retries — use `--resume` instead.

### Issue 8: `subprocess_timeout` defined in two config dataclasses

**Symptom:** No runtime error — just a confusing dead field.
**Detail:** `subprocess_timeout` was in both `EvaluationConfig` and `ExecutionConfig`. Only `ExecutionConfig` was consumed by code. The `EvaluationConfig` version was parsed from YAML but never read.
**Fix applied:** Removed from `EvaluationConfig`. Removed from eval parsing.
**Prevention:** Config fields should be audited for consumption whenever a field is added. The allow-list pattern in `_KNOWN_EXEC_FIELDS` provides partial protection but only for execution config.

---

## Pattern Analysis

### Root causes cluster into 3 categories:

**1. Config wiring gaps (Issues 1, 3, 8)**
Adding a config field requires touching too many places. The allow-list, dataclass, parser, and consumer are all separate and can drift.

**2. Path resolution fragility (Issues 4, 5, 6, 7)**
The file reorg moved directories but path resolution is scattered across many files with different mechanisms (config paths, PYTHONPATH, sys.path, module imports, file-based imports). Each mechanism broke independently.

**3. Divergent code paths for same function (Issue 6)**
Preflight and execution test discovery use different mechanisms. One survived the reorg, the other didn't. The preflight gave false confidence.

---

## Recommendations

1. **Derive `_KNOWN_EXEC_FIELDS` from dataclass** — no manual allow-list
2. **Auto-generate component metadata** from template AST — no hand-maintenance
3. **Unify test discovery** — preflight and execution must use the same function
4. **Add `import os` to `run_case.py` imports permanently** — it's a subprocess that manipulates paths
5. **Never change `cases_v2.json` code_files paths** — they are prompt-facing contract
6. **Add end-to-end smoke test gate** before every ablation launch — 1 case, 1 trial, verify pass/fail is real
7. **Orchestrator should `mkdir -p` on run_dir** before manifest write

---

## Current Status

A 100-worker run is in progress (375/1740 as of last check). The `os` import fix and path fixes are applied. Previous failed runs (5 total) were caused by the issues above, not by the v3 prompts themselves.
