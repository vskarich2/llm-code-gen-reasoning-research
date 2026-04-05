"""V4 FINAL calibration: fix remaining instant-pattern A's, solution-hint B's, ambiguity-weak C's.

Run: .venv/bin/python scripts/enrich_task_prompts_v4_final.py
"""

import json
from pathlib import Path

SPLIT_DIR = Path("case_data/cases_split")
F = {}

# ============================================================
# A FIXES: reduce instant pattern matching
# ============================================================

# index_misalign_a: remove "label correct but value wrong" → too structural
F["index_misalign_a"] = {
    "enriched_task_prompt":
        "After inserting a new entry at position 0, get_entry(0) returns an unexpected value. "
        "The retrieved data does not correspond to what was inserted at that position. "
        "Investigate why the data association breaks after positional insertion in add_entry.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'label correct but value from different entry' instantly maps to parallel-array "
        "desynchronization — a well-known pattern. "
        "FIX: removed the structural hint (label vs value). Now says 'unexpected value' and "
        "'data association breaks' which requires the model to inspect the data structures. "
        "LEAKAGE HONESTY: naming add_entry and positional insertion still narrows to the function "
        "and operation, but the model must determine HOW the association breaks. "
        "DIFFICULTY: A — function named, one reasoning step to find insert-vs-append mismatch.",
}

# mutable_default_a: "accumulation across calls" is the diagnosis
F["mutable_default_a"] = {
    "enriched_task_prompt":
        "Calling enqueue twice with different tasks produces unexpected results — the second "
        "call returns 2 items when only 1 was provided. Investigate why the function appears "
        "to retain state from previous invocations.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'items from the first call' + 'accumulation' instantly diagnoses mutable default. "
        "FIX: says 'appears to retain state' rather than naming the accumulation mechanism. "
        "LEAKAGE HONESTY: 'retain state from previous invocations' still strongly suggests a "
        "persistent-state bug, but the model must determine whether it's a mutable default, "
        "a module-level variable, a closure, or a class attribute. One reasoning step remains. "
        "DIFFICULTY: A — function named, symptom given, mechanism class implied but not specified.",
}

# stale_cache_a: "write then stale read" is instant diagnosis
F["stale_cache_a"] = {
    "enriched_task_prompt":
        "After calling update_product with a new price, get_product returns the old price "
        "(10.0 instead of 25.0). Investigate why the updated value is not visible to reads.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'Fix the catalog so that reads reflect the latest writes' encodes the "
        "read-after-write invariant too directly — model jumps to cache invalidation. "
        "FIX: now says 'investigate why the updated value is not visible' which requires "
        "the model to determine the cause (could be caching, could be write failure, could be "
        "read path issue). "
        "LEAKAGE HONESTY: naming both functions and the exact stale value still strongly narrows "
        "the search. Appropriate for A — but now requires identifying the caching mechanism "
        "rather than being handed the read-write consistency invariant.",
}

# wrong_condition_a: "one extra at boundary" is instant off-by-one
F["wrong_condition_a"] = {
    "enriched_task_prompt":
        "The rate limiter's is_rate_limited function returns incorrect results at the boundary "
        "— when the request count equals the limit, the function reports 'not limited'. "
        "Fix the boundary check in is_rate_limited.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'allows one extra request beyond the limit' instantly diagnoses off-by-one. "
        "FIX: says 'returns incorrect results at the boundary' and 'count equals the limit' which "
        "describes the failing condition without saying 'off-by-one' or 'one extra'. The model "
        "must inspect the comparison operator. "
        "LEAKAGE HONESTY: 'boundary check' is close to the fix location but doesn't specify "
        "the operator change. Appropriate for A — function named, one inspection step. "
        "DIFFICULTY: A.",
}

# ============================================================
# B FIXES: remove solution-structure hints
# ============================================================

# partial_update_b: "derived values" names the bug class
F["partial_update_b"] = {
    "enriched_task_prompt":
        "After updating user profile fields, some data becomes inconsistent — values that "
        "should reflect the updated fields still show old data. The system uses profile.py "
        "and validation.py. Fix the profile update logic.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'derived values are not recalculated' names the bug class (derived field sync). "
        "FIX: now says 'some data becomes inconsistent' without categorizing the relationship "
        "between the fields. The model must determine that full_name is derived from first+last "
        "by inspecting the code. "
        "LEAKAGE HONESTY: 'values that should reflect the updated fields' still hints at "
        "field dependency, but does not name it as a derived-value pattern. "
        "DIFFICULTY: B — two files, model must classify the bug type.",
}

# lazy_init_b: "propagate correctly" encodes the fix
F["lazy_init_b"] = {
    "enriched_task_prompt":
        "After resetting configuration, the client module still returns old values. "
        "The system uses config.py and client.py. Investigate why the reset does not "
        "take effect in the client.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'configuration resets propagate correctly' encodes the propagation fix. "
        "FIX: now says 'investigate why the reset does not take effect' — asks for diagnosis "
        "rather than prescribing propagation. "
        "LEAKAGE HONESTY: 'client module still returns old values' narrows to the client, "
        "but the model must determine whether the client caches, imports eagerly, or has "
        "its own config source. "
        "DIFFICULTY: B — two files, model must identify the capture mechanism.",
}

# index_misalign_b: "all report structures remain consistent" encodes invariant
F["index_misalign_b"] = {
    "enriched_task_prompt":
        "After deleting a column from the report, row data appears under the wrong headers — "
        "values are shifted relative to their expected columns. The system uses report.py "
        "and data.py. Fix the column deletion logic.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'all report structures remain consistent' directly names the parallel-structure "
        "invariant. "
        "FIX: now says 'values are shifted relative to expected columns' which describes the "
        "visible symptom without naming the structural invariant. The model must determine "
        "that multiple parallel structures (headers, rows) need coordinated updates. "
        "DIFFICULTY: B — two files, model must find the incomplete deletion.",
}

# mutable_default_b: "each batch processes all its tasks independently" encodes invariant
F["mutable_default_b"] = {
    "enriched_task_prompt":
        "When processing batches sequentially, valid tasks from the second batch are skipped — "
        "tasks that appeared in a previous batch are not processed again. The system uses "
        "worker.py and queue.py. Investigate why previously-seen tasks are being filtered.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'each batch processes all its tasks independently' prescribes the invariant. "
        "FIX: now says 'investigate why previously-seen tasks are being filtered' which asks "
        "for diagnosis. The model must find the filtering mechanism (the stale seen set). "
        "LEAKAGE HONESTY: 'previously-seen tasks are being filtered' hints strongly at a "
        "deduplication mechanism, but doesn't reveal it's a mutable default parameter. "
        "DIFFICULTY: B — two files, model must identify the persistence mechanism.",
}

# ============================================================
# C FIXES: enforce true causal ambiguity
# ============================================================

# alias_config_c: add alternate hypothesis
F["alias_config_c"] = {
    "enriched_task_prompt":
        "Requests served by the middleware observe configuration values set during previous "
        "requests — for example, a debug override persists into the next request. The system "
        "spans config.py, middleware.py, and handler.py. The middleware caches configuration "
        "and the handler applies overrides. Fix the configuration flow so that each request "
        "starts with clean state.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: only one plausible cause (config sharing in create_config). "
        "FIX: now mentions that 'middleware caches configuration' AND 'handler applies overrides' "
        "— creating two plausible sources: (1) the cache in middleware retains state, or "
        "(2) the override in handler mutates shared state. The actual bug is in config.py "
        "(neither of these), but the prompt creates two plausible alternate hypotheses. "
        "CAUSAL AMBIGUITY: middleware caching vs handler override mutation vs config source. "
        "DIFFICULTY: C — three files, three plausible locations.",
}

# early_return_c: "all charge paths" narrows too much
F["early_return_c"] = {
    "enriched_task_prompt":
        "The audit trail is incomplete — verification reports fewer entries than expected after "
        "a series of charge operations. The system involves payment.py, ledger.py, and audit.py, "
        "with caching and recording happening at different stages. Investigate why some "
        "operations are not being recorded.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'across all charge paths' narrows to path-coverage analysis. "
        "FIX: now says 'caching and recording happening at different stages' which creates "
        "ambiguity: is the issue in the caching logic? The recording logic? The audit module? "
        "The interaction between stages? "
        "CAUSAL AMBIGUITY: (1) caching prevents recording, (2) recording skips some operations, "
        "(3) audit module drops entries, (4) stage ordering causes misses. "
        "DIFFICULTY: C — three files, multiple plausible stages.",
}

# retry_dup_c: obvious retry duplication
F["retry_dup_c"] = {
    "enriched_task_prompt":
        "Messages are being delivered multiple times. The duplication count varies — sometimes "
        "2, sometimes more. The system involves pipeline.py, sender.py, and store.py, with "
        "retry logic at multiple levels. Investigate why the delivery count is inconsistent.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'sometimes 2, sometimes more' was already present but the prompt lacked "
        "alternate hypotheses. "
        "FIX: added 'retry logic at multiple levels' which creates ambiguity about which level "
        "causes the duplication: (1) pipeline-level retry, (2) sender-level retry, (3) store "
        "not being idempotent, (4) interaction between retry levels. The variable count hints "
        "at compounding but doesn't reveal the nesting structure. "
        "CAUSAL AMBIGUITY: pipeline retry vs sender retry vs store idempotency vs interaction. "
        "DIFFICULTY: C — three files, multiple retry levels.",
}

# temporal_drift_c: normalization too obvious
F["temporal_drift_c"] = {
    "enriched_task_prompt":
        "The report shows incorrect raw metrics — values that should be in the hundreds appear "
        "as approximately 1.0. The system involves pipeline.py, transforms.py, and metrics.py, "
        "with data flowing through multiple transformation stages before metrics are computed. "
        "Fix the data flow so that raw metrics reflect the original input.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: the normalization cause was too obvious from '1.0 instead of hundreds'. "
        "FIX: added 'multiple transformation stages before metrics are computed' which creates "
        "ambiguity: (1) metrics computed on wrong stage data, (2) transformation corrupts data, "
        "(3) metrics function itself normalizes, (4) data flow routing sends wrong input. "
        "CAUSAL AMBIGUITY: wrong stage vs corrupted transform vs metrics bug vs routing. "
        "DIFFICULTY: C — three files, pipeline with multiple stages.",
}

# wrong_condition_c: condition logic too obvious
F["wrong_condition_c"] = {
    "enriched_task_prompt":
        "The authorization logic produces incorrect results for certain user/token combinations. "
        "Specifically, expired tokens are accepted when they should be rejected, but only for "
        "some user categories. The system involves limiter.py, policy.py, and middleware.py. "
        "Fix the authorization logic.",

    "enriched_task_prompt_justification":
        "V3 ISSUE: 'expiry should always block regardless of exemption' directly stated the "
        "precedence rule, making the operator-precedence fix obvious. "
        "FIX: now says 'only for some user categories' which creates ambiguity: is it a "
        "per-category configuration issue? A conditional logic error? A middleware bypass? "
        "An exemption policy bug? The model must trace the logic to find the precedence error. "
        "CAUSAL AMBIGUITY: category config vs conditional logic vs middleware vs policy. "
        "DIFFICULTY: C — three files, multiple plausible logic errors.",
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
            if cid in F:
                case["enriched_task_prompt"] = F[cid]["enriched_task_prompt"]
                case["enriched_task_prompt_justification"] = F[cid]["enriched_task_prompt_justification"]
                fixed += 1
                modified = True
        if modified:
            fpath.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    print(f"Total: {total}, Fixed: {fixed}, Unchanged: {total - fixed}")
    print(f"A fixes: index_misalign_a, mutable_default_a, stale_cache_a, wrong_condition_a")
    print(f"B fixes: partial_update_b, lazy_init_b, index_misalign_b, mutable_default_b")
    print(f"C fixes: alias_config_c, early_return_c, retry_dup_c, temporal_drift_c, wrong_condition_c")


if __name__ == "__main__":
    main()
