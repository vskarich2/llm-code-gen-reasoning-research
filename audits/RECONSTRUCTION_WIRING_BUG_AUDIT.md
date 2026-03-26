# AUDIT: Reconstruction Wiring Bug — Zero Pass Rate Across All Models

**Date:** 2026-03-25
**Severity:** CRITICAL — all ablation data collected prior to this date is invalid
**Cost:** ~$20 in wasted API calls (24 workers, 3 models x 8 trials x 58 cases x 2 conditions = 2,784 eval calls)
**Status:** Root cause identified, partial fix applied, validation pending

---

## 1. Symptom

The LEG ablation (3 models, 8 trials, 2 conditions) showed **0.000 pass rate** across every model, every condition, every case. No model solved a single case. This is implausible given that models were producing reasonable reasoning and code.

Dashboard showed:
- Pass rate: 0.0000 (all conditions, all models)
- Lucky fix rate: 0.0000
- Exec|Reasoning (E|R): 0.0000
- LEG rate: ~0.47–0.93 (high, but this is because reasoning_correct was computed correctly while code_correct was always False)

## 2. Root Cause

**The reconstructed code from file-dict model responses was never wired into the evaluation pipeline.**

### The Bug (execution.py, _attempt_and_evaluate, ~line 200)

When models return the multi-file `files` dict format (e.g., `{"reasoning": "...", "files": {"path/to/file.py": "code..."}}`), the parse pipeline works as follows:

1. `parse_model_response()` in `parse.py` routes to `_try_file_dict()` (line 171)
2. `_try_file_dict()` returns `{"code": None, "files": {...}, "response_format": "file_dict"}`
3. Back in `_attempt_and_evaluate()`, the reconstructor runs successfully:
   ```python
   recon = reconstruct_strict(manifest_paths, manifest_files, parsed["files"])
   parsed["_reconstruction"] = recon
   parsed["_reconstruction_status"] = recon.status
   ```
4. **BUG: The reconstructed code is stored in `parsed["_reconstruction"]` but `parsed["code"]` remains `None`.**
5. `evaluate_output()` in `evaluator.py` reads `parsed["code"]` (line 441) — gets `None`
6. `exec_evaluate()` in `exec_eval.py` checks `if not code or len(code.strip()) < 10:` (line 762) — `None` is falsy
7. Immediately returns `{"pass": False, "ran": False, "reasons": ["no extractable code in output"]}`

### Why This Affected Every Baseline Case

The prompt system instructs models to return the `files` dict format (via `file_paths` parameter passed to `call_model`). All three models (gpt-5.4-mini, gpt-5-mini, gpt-4o-mini) complied and returned valid file-dict responses. The reconstructor existed and ran — but its output was orphaned.

### Why leg_reduction Was Partially Different

The `run_leg_reduction()` path in `execution.py` (line 429) uses its own parsing (`parse_leg_reduction_output`) which extracts `code` as a string directly, bypassing the file-dict format. So leg_reduction cases did attempt execution — but many still failed with runtime errors because the leg_reduction parser builds a single code string that may not assemble correctly for multi-file cases.

## 3. Data Triage — What Is Salvageable?

### Completely Invalid (must discard)
- **All `pass`, `code_correct`, `score` values** — these are all False/0.0 due to the bug, not due to model behavior
- **All `execution` metadata** — `ran: False` or `status: error` for infrastructure reasons, not model quality
- **All derived metrics**: pass rate, lucky fix rate, E|R, intervention delta on pass

### Partially Valid (use with caution)
- **`reasoning_correct`** — This was computed by an independent LLM classifier that evaluates reasoning quality without running code. These values may be valid, but the classifier received `code: None` as input, which could have biased its assessment (the prompt includes the code).
- **`failure_type`** — Same caveat as reasoning_correct; the classifier saw no code.
- **LEG rate** — The high LEG rates (0.47–0.93) are *directionally* interesting but cannot be trusted because `code_correct` was artificially always False.

### Completely Valid
- **Model response content** — The raw responses in `run_responses.jsonl` files are valid artifacts. Models did produce code.
- **Timing data** — API latency and throughput measurements are real.
- **Infrastructure validation** — The process-based runner, dashboard, log integrity system all worked correctly. The bug was in the evaluation pipeline, not the orchestration.

## 4. Why This Wasn't Caught

1. **No integration test for the file-dict -> reconstruct -> evaluate path.** The reconstructor was tested in isolation. The evaluator was tested in isolation. The wiring between them was never tested end-to-end.

2. **The smoke test passed** — because the smoke test only checked that workers completed without crashing. It did not assert any non-zero pass rate. A smoke test that asserts `pass_rate > 0 for at least 1 case` would have caught this immediately.

3. **The dashboard showed plausible-looking LEG metrics** — because `reasoning_correct` was computed independently and correctly. The 0.0 pass rate looked like "models can't solve these cases" rather than "evaluation is broken." The dashboard had no alert for `ran=False` on every case.

4. **The `_reconstruction` field was populated correctly** — so any debugging that checked "did reconstruction work?" would see SUCCESS. The disconnect was that SUCCESS didn't flow into the evaluation.

## 5. Fix Plan

### Fix 1: Wire reconstruction into parsed["code"] (DONE - partial)

In `execution.py`, `_attempt_and_evaluate()`, after successful reconstruction:

```python
if recon.status == "SUCCESS":
    parsed["_reconstruction_error"] = False
    # Wire reconstructed files into parsed["code"] so exec_evaluate can run them
    parsed["code"] = "\n\n".join(recon.files[p] for p in manifest_paths if p in recon.files)
```

**Status:** Applied but not fully validated. The single-case smoke test (`alias_config_a`) showed:
- Code now runs (`ran: True`)
- Real runtime error occurs (`'module' object is not subscriptable`) — this is a genuine model code bug, not infrastructure
- Score went from 0.0 to 0.1
- Category correctly classified as `leg` (reasoning correct, code incorrect)

### Fix 2: Validate the concatenation approach

**CONCERN:** Simply concatenating all files with `\n\n` may not work for all cases. Multi-file cases have cross-file imports. The `strip_local_imports` function in `parse.py` handles this for single-code-string input, but we need to verify:
- Does `exec_evaluate` -> `_assemble_program` -> `load_module_from_code` handle concatenated multi-file code correctly?
- Are there ordering dependencies between files?
- Does `strip_local_imports` correctly remove cross-file imports when files are concatenated?

**Action:** Read `_assemble_program` to understand the existing multi-file assembly logic and confirm that the concatenated code path is compatible.

### Fix 3: Add smoke test assertion for non-zero pass rate

Before any future ablation run, the smoke test must assert:
```
assert pass_rate > 0 for at least 1 case out of N smoke cases
```
If zero cases pass across all models, something is broken. This should be a hard gate that prevents the full ablation from launching.

### Fix 4: Add dashboard alert for universal ran=False

The dashboard should flag if >90% of cases have `ran=False`. This is never a valid experimental outcome — it always indicates a pipeline failure.

### Fix 5: Re-run the ablation

After fixes 1-4 are validated:
1. Clean out invalid run data from `logs/ablation_runs/`
2. Re-run full ablation with the fixed pipeline
3. Verify first trial shows non-zero pass rate before letting all 24 workers run

## 6. Remaining Questions

1. **Is concatenation sufficient?** The reconstructor returns ordered files. But `exec_evaluate` has its own `_assemble_program` function that may expect a different input format. Need to verify these aren't fighting each other.

2. **What about failed reconstructions?** When `recon.status != "SUCCESS"`, `parsed["code"]` stays `None`. These cases will still score 0. Is that correct, or should we fall back to concatenating the raw `parsed["files"]` values?

3. **Should the leg_reduction path also use reconstruction?** Currently it has its own parser that extracts a single code string. If models return file-dict format in the leg_reduction prompt, the same bug could apply there.

## 7. Files Involved

| File | Line(s) | Role |
|------|---------|------|
| `execution.py` | 199-215 | **BUG SITE** — reconstruction runs but code not wired back |
| `parse.py` | 171-194 | `_try_file_dict` returns `code: None` for file-dict format |
| `evaluator.py` | 441 | Reads `parsed["code"]` — gets None |
| `exec_eval.py` | 762 | Guards on `not code` — immediately fails |
| `reconstructor.py` | 27-115 | Reconstruction logic — works correctly, output orphaned |
| `execution.py` | 429-494 | `run_leg_reduction` — separate path, partially affected |
