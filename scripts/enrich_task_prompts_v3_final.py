"""V3 final calibration: fix remaining A-too-easy, C-insufficient-ambiguity, honest justifications.

Only touches cases that need adjustment. Does not regress already-good calibrations.

Run: .venv/bin/python scripts/enrich_task_prompts_v3_final.py
"""

import json
from pathlib import Path

SPLIT_DIR = Path("case_data/cases_split")

# Only cases that need recalibration
FIXES = {}

# ── effect_order_a: "counts match item counts" encodes the fix ──
FIXES["effect_order_a"] = {
    "enriched_task_prompt":
        "After process_batch processes 3 items, only 1 snapshot is recorded instead of 3. "
        "There is an inconsistency between the batch processing results and the recorded snapshots. "
        "Fix the implementation so that the snapshot record is consistent with processing.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'snapshot counts match item counts' directly "
        "encodes the per-item invariant. "
        "SYMPTOM: 'expected 3 snapshots (one per item), got 1'. "
        "INCLUDED: the function name, the exact count mismatch (3 vs 1). "
        "WITHHELD: the per-item placement requirement, the batch-level vs per-item distinction. "
        "The wording 'consistent with processing' requires the model to infer what consistency "
        "means — it could be timing, ordering, or granularity. "
        "LEAKAGE HONESTY: the 3-vs-1 count strongly suggests a granularity issue, but does not "
        "directly say 'move snapshot inside the loop'. One reasoning step remains. "
        "DIFFICULTY: A — function named, counts given, but mechanism not prescribed. "
        "FAMILY: B says 'significantly lower' without exact counts; C says 'fewer than expected'.",
}

# ── early_return_a: "consistent with the number of calls" is invariant-as-instruction ──
FIXES["early_return_a"] = {
    "enriched_task_prompt":
        "The payment processor's ledger verification fails. After processing two payments "
        "(including one for amount zero), verify_ledger reports a count mismatch — the ledger "
        "has fewer entries than expected. Investigate why some payments are not being recorded.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'consistent with the number of payment calls' "
        "directly encodes the one-entry-per-call invariant. "
        "SYMPTOM: 'verify_ledger(2) returned False — zero-amount payment not recorded'. "
        "INCLUDED: the function name, the zero-amount trigger, the count mismatch. "
        "WITHHELD: that a specific early-return path skips the ledger append. The new ending "
        "'investigate why some payments are not being recorded' asks the model to diagnose "
        "rather than prescribing the invariant. "
        "LEAKAGE HONESTY: mentioning the zero-amount case strongly narrows the search to the "
        "zero-amount code path. This is appropriate for A — one reasoning step remains "
        "(finding the early return on that path). "
        "DIFFICULTY: A — trigger + function named, model must find the skip. "
        "FAMILY: B says 'certain transaction patterns' without naming zero-amount; "
        "C says 'all charge paths' abstractly.",
}

# ── partial_update_a: "stays consistent" is invariant-as-instruction ──
FIXES["partial_update_a"] = {
    "enriched_task_prompt":
        "After updating a user's name via update_profile, the display_name field still shows "
        "the old value ('Alice' instead of 'Bob'). Investigate why the display_name is not "
        "being updated.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'so that dependent fields stay consistent' "
        "encodes the synchronization invariant. "
        "SYMPTOM: 'display_name not synced: display_name=Alice, expected Bob'. "
        "INCLUDED: the function name, the specific stale field, concrete values. "
        "WITHHELD: that display_name is a derived field requiring synchronization. "
        "The model must determine that display_name should be updated when name changes — "
        "this is the diagnosis step. "
        "LEAKAGE HONESTY: naming both the function and the stale field makes the fix nearly "
        "obvious for A — this is appropriate since the model still must add the update line. "
        "DIFFICULTY: A — highly localized. "
        "FAMILY: B says 'derived values' abstractly; C says 'dependent state' across three files.",
}

# ── mutable_default_a: "each call operates independently" is invariant ──
FIXES["mutable_default_a"] = {
    "enriched_task_prompt":
        "Calling enqueue twice with different tasks produces unexpected accumulation — the second "
        "call's result contains items from the first call (got 2 items, expected 1). "
        "Investigate why state persists between separate calls to enqueue.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'each call operates independently' directly "
        "prescribes the invariant. "
        "SYMPTOM: 'second enqueue() leaked state: got 2 items, expected 1'. "
        "INCLUDED: the function name, the accumulation symptom with concrete count. "
        "WITHHELD: the mutable default mechanism, the parameter name (queue=[]), the fix. "
        "'Investigate why state persists' asks the model to diagnose rather than prescribing "
        "the independence invariant. "
        "LEAKAGE HONESTY: naming the function and the cross-call persistence strongly narrows "
        "to the parameter or closure level. Appropriate for A. "
        "DIFFICULTY: A — function + symptom, one step to mechanism. "
        "FAMILY: B says 'certain tasks skipped' without naming function; C is cross-module.",
}

# ── use_before_set_a: "each call is independent" is invariant ──
FIXES["use_before_set_a"] = {
    "enriched_task_prompt":
        "The transform function returns stale results when called with an empty list — it "
        "produces output from a previous call ([2, 4, 6]) instead of an empty result. "
        "Investigate why previous results appear on subsequent calls with different input.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'each call is independent of prior calls' "
        "prescribes the invariant. "
        "SYMPTOM: 'transform([]) returned [2, 4, 6], expected []'. "
        "INCLUDED: the function name, the concrete stale output. "
        "WITHHELD: the uninitialized variable mechanism. 'Investigate why previous results "
        "appear' asks for diagnosis. "
        "LEAKAGE HONESTY: the stale-on-empty-input pattern strongly suggests a variable "
        "initialization issue. Appropriate for A. "
        "DIFFICULTY: A — function + symptom, one step. "
        "FAMILY: B mentions files; C is abstract across three files.",
}

# ── index_misalign_a: "correctly paired" / "remain correctly paired" encodes fix ──
FIXES["index_misalign_a"] = {
    "enriched_task_prompt":
        "After inserting a new entry at position 0, get_entry(0) returns the wrong value — "
        "the label is correct ('gamma') but the associated value is 10 instead of 30. "
        "Investigate why the label-value association breaks after positional insertion.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. V2 ISSUE: 'labels and values remain correctly paired' "
        "directly names the parallel-array invariant. "
        "SYMPTOM: 'get_entry(0) returned (gamma, 10), expected (gamma, 30)'. "
        "INCLUDED: the function, the operation (insert at position 0), the concrete mismatch. "
        "WITHHELD: that labels and values use different insertion strategies (insert vs append). "
        "'Investigate why the association breaks' asks for diagnosis without naming the "
        "parallel-array pattern. "
        "LEAKAGE HONESTY: the concrete mismatch (right label, wrong value) strongly implies "
        "a desynchronization in parallel structures. Appropriate for A. "
        "DIFFICULTY: A. FAMILY: B describes column deletion; C describes validation failure.",
}

# ── effect_order_c: needs more causal ambiguity ──
# Current: "Audit completeness checks fail after batch processing"
# Issue: only one plausible explanation (batch-level emission)
# Fix: introduce the fast_process trap as an alternate path
FIXES["effect_order_c"] = {
    "enriched_task_prompt":
        "Audit completeness checks fail after batch processing — recorded entries are fewer "
        "than expected. The system has both standard and optimized processing paths across "
        "processor.py, metrics.py, and audit.py. Fix the implementation so that auditing "
        "accurately reflects actual processing.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Audit log has fewer entries than items' — accurate. "
        "SYMPTOM: 'expected 3 audit entries (one per item), got 1'. "
        "INCLUDED: the count mismatch, three files, and the existence of multiple paths. "
        "WITHHELD: which path is wrong, whether the issue is in the standard path or the "
        "optimized path, the batch-level emission. "
        "CAUSAL AMBIGUITY: mentioning 'standard and optimized processing paths' creates "
        "two plausible hypotheses — (1) the standard path emits wrong granularity, or "
        "(2) the optimized path skips auditing entirely. The model must trace both. "
        "LEAKAGE HONESTY: 'fewer than expected' avoids encoding per-item granularity. "
        "DIFFICULTY: C — three files, two plausible paths, trap preserved. "
        "FAMILY: A gives function + exact counts; B gives files + approximate; "
        "C adds path ambiguity.",
}

# ── stale_cache_c: needs more ambiguity about which layer ──
FIXES["stale_cache_c"] = {
    "enriched_task_prompt":
        "The API returns outdated product data after updates, even though some cache layers "
        "appear to be correctly invalidated. The system uses catalog.py, cache.py, and api.py "
        "with multiple caching layers. Fix the implementation so that updates are visible "
        "to all read paths.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'API returns stale product data' — accurate. V2 was good but could increase "
        "ambiguity about which layer is the problem. "
        "SYMPTOM: 'stale local cache: price=10.0, expected 50.0'. "
        "INCLUDED: the stale symptom, three files, multi-layer hint, and crucially 'some cache "
        "layers appear to be correctly invalidated' — this introduces the key ambiguity. "
        "WITHHELD: which layer is missed (local), which invalidation works (shared). "
        "CAUSAL AMBIGUITY: the model must determine which of the multiple layers is stale — "
        "is it the API-level cache? The shared cache? A local per-request cache? The DB itself? "
        "LEAKAGE HONESTY: 'some layers correctly invalidated' narrows slightly but preserves "
        "the question of which layer. "
        "DIFFICULTY: C — multi-layer, partial-invalidation ambiguity. "
        "FAMILY: A names functions; B names files; C adds layer ambiguity.",
}

# ── lazy_init_c: needs causal ambiguity about which module captures ──
FIXES["lazy_init_c"] = {
    "enriched_task_prompt":
        "Configuration changes do not propagate through the system. After a reset, multiple "
        "values across different components remain stale. The system spans config.py, client.py, "
        "and handler.py, each of which may read configuration independently. "
        "Fix the implementation so that resets take full effect.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Config reset doesn't propagate through client to handler' — named the chain. "
        "SYMPTOM: 'api_key stale, base_url stale'. "
        "INCLUDED: the multi-value stale symptom, three files, the hint that each module may "
        "read config independently (creates ambiguity about where caching occurs). "
        "WITHHELD: the propagation direction (config→client→handler), which file captures "
        "eagerly, the client.refresh() trap. "
        "CAUSAL AMBIGUITY: 'each may read independently' means the stale value could be "
        "cached in config.py, client.py, or handler.py. The model must trace all three. "
        "LEAKAGE HONESTY: this is genuinely ambiguous — the model cannot determine the "
        "capture location from the prompt alone. "
        "DIFFICULTY: C. FAMILY: A names function; B names files; C adds per-module ambiguity.",
}

# ── mutable_default_c: needs causal ambiguity ──
FIXES["mutable_default_c"] = {
    "enriched_task_prompt":
        "Job history leaks between independently scheduled jobs — a job scheduled after another "
        "inherits history entries it should not have. The system involves scheduler.py, worker.py, "
        "and queue.py, which share state through function calls and decorators. "
        "Fix the implementation so that jobs have isolated state.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Scheduler history is shared across jobs' — accurate. "
        "SYMPTOM: 'schedule_batch history leaked from schedule_one'. "
        "INCLUDED: the cross-job leakage, three files, and the hint that state sharing involves "
        "'function calls and decorators' — this creates ambiguity about the mechanism. "
        "WITHHELD: the specific decorator closure, the shared mutable list, the function name. "
        "CAUSAL AMBIGUITY: the state could leak through (1) a module-level variable, "
        "(2) a mutable default parameter, (3) a closure variable in a decorator, or "
        "(4) shared queue state. The model must inspect all mechanisms. "
        "LEAKAGE HONESTY: mentioning decorators narrows somewhat but does not identify "
        "which decorator or how it captures state. "
        "DIFFICULTY: C. FAMILY: A names function; B names files; C adds mechanism ambiguity.",
}

# ── partial_update_c: needs ambiguity about which fields ──
FIXES["partial_update_c"] = {
    "enriched_task_prompt":
        "After modifying user profile fields, some dependent state is not refreshed — flags "
        "and cached values remain stale. The system involves profile.py, validation.py, and "
        "notifications.py. Investigate which dependent state is affected and fix the update "
        "logic.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'After changing email, old greeting still shows' — missed verified flag. "
        "SYMPTOM: 'verified not reset: verified=True, expected False'. "
        "INCLUDED: the abstract multi-field staleness, three files. "
        "WITHHELD: which fields (verified, cached_greeting), which trigger (email change), "
        "the validate_email trap. "
        "CAUSAL AMBIGUITY: 'some dependent state' could be any combination of verified, "
        "display_name, cached_greeting, or other fields. The model must inspect the update "
        "logic to find which dependencies are missed. "
        "DIFFICULTY: C. FAMILY: A names function + specific field; B names files + 'derived "
        "values'; C adds 'investigate which' — requiring enumeration.",
}

# ── commit_gate: currently doesn't mention files ──
FIXES["commit_gate"] = {
    "enriched_task_prompt":
        "After simplifying the pipeline by removing steps that appeared redundant, the committed "
        "total is null and the view does not reflect the committed data. The system spans "
        "pipeline.py, state.py, reducers.py, selectors.py, and api.py. Restore the pipeline "
        "steps necessary for correct state transitions.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Restore the necessary steps' — honest framing. V2 ISSUE: did not mention "
        "the five files, reducing the cross-file search aspect. "
        "SYMPTOM: 'committed total is null'. "
        "INCLUDED: that steps were removed, two broken invariants (total + view), five files. "
        "WITHHELD: which functions (commit, freeze_view), why they're independently necessary. "
        "CAUSAL AMBIGUITY: with five files, the model must determine which file(s) need changes "
        "and which steps were removed. "
        "DIFFICULTY: L3 — the trap is restoring only one of the two functions.",
}


def main():
    files = sorted(SPLIT_DIR.glob("*.json"))
    total = 0
    fixed = 0

    for fpath in files:
        cases = json.loads(fpath.read_text())
        modified = False
        for case in cases:
            cid = case.get("id")
            total += 1
            if cid in FIXES:
                case["enriched_task_prompt"] = FIXES[cid]["enriched_task_prompt"]
                case["enriched_task_prompt_justification"] = FIXES[cid]["enriched_task_prompt_justification"]
                fixed += 1
                modified = True
        if modified:
            fpath.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    print(f"Total cases: {total}")
    print(f"Recalibrated: {fixed}")
    print(f"Unchanged: {total - fixed}")
    print(f"\nFixed cases: {sorted(FIXES.keys())}")


if __name__ == "__main__":
    main()
