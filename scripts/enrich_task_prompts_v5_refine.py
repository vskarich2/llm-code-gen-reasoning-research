"""V5 final refinement: remove mechanism hinting, directional language, strict honesty.

Only touches cases with identified issues. Minimal changes.

Run: .venv/bin/python scripts/enrich_task_prompts_v5_refine.py
"""

import json
from pathlib import Path

SPLIT_DIR = Path("case_data/cases_split")
F = {}

# ── mutable_default_a: "retain state from previous invocations" hints mechanism ──
F["mutable_default_a"] = {
    "enriched_task_prompt":
        "Calling enqueue twice with different tasks produces unexpected results — the second "
        "call returns 2 items when only 1 was provided. Investigate why the output includes "
        "data not provided in the current call.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'appears to retain state from previous invocations' names the mechanism class "
        "(state persistence). "
        "FIX: replaced with 'output includes data not provided in the current call' — describes "
        "the observable output without naming internal behavior. The model must determine whether "
        "the source is a mutable default, module-level variable, closure, or class attribute. "
        "LEAKAGE HONESTY: the 2-instead-of-1 count still strongly suggests accumulation, but "
        "the prompt no longer names the persistence mechanism. "
        "DIFFICULTY: A — function named, one reasoning step.",
}

# ── use_before_set_a: "from a previous call" hints mechanism ──
F["use_before_set_a"] = {
    "enriched_task_prompt":
        "The transform function returns unexpected results when called with an empty list — "
        "it produces [2, 4, 6] instead of []. Investigate why the output contains values "
        "that were not derived from the current input.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'from a previous call' directly names cross-call state leakage. "
        "FIX: replaced with 'values not derived from the current input' — describes the "
        "observable mismatch without attributing it to prior calls. The model must discover "
        "the cross-call relationship by inspecting variable initialization. "
        "LEAKAGE HONESTY: the specific stale output [2, 4, 6] from empty input strongly "
        "suggests leftover state, but the prompt does not name the temporal relationship. "
        "DIFFICULTY: A — function named, one inspection step.",
}

# ── alias_config_b: "state persists incorrectly between calls" hints mechanism ──
F["alias_config_b"] = {
    "enriched_task_prompt":
        "After modifying settings returned by the config system, subsequent calls reflect "
        "those modifications instead of returning fresh defaults. The config flow involves "
        "create_config, get_settings, and merge_overrides. Identify what is causing the "
        "incorrect behavior and fix it.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'Configuration state persists incorrectly between calls' names the mechanism "
        "(state persistence). "
        "FIX: removed the leading sentence. Now starts with the observable behavior (modifications "
        "reflected in subsequent calls). The model must classify this as a state-sharing problem "
        "by inspecting the three functions. "
        "LEAKAGE HONESTY: 'subsequent calls reflect those modifications' still suggests shared "
        "state, but does not name persistence as the mechanism — it could be intentional caching, "
        "shared references, or incorrect write-through. "
        "DIFFICULTY: B — three candidate functions, no mechanism named. "
        "FAMILY: A names create_config directly; C names only files.",
}

# ── mutable_default_c: "leaks between" hints mechanism ──
F["mutable_default_c"] = {
    "enriched_task_prompt":
        "Jobs scheduled independently produce unexpected cross-contamination — a job scheduled "
        "after another contains history entries it should not have. The system involves "
        "scheduler.py, worker.py, and queue.py, which interact through function calls and "
        "decorators. Fix the implementation so that jobs have isolated state.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'Job history leaks between independently scheduled jobs' uses 'leaks' which "
        "names the mechanism class. "
        "FIX: replaced with 'cross-contamination' — describes the observable effect without "
        "naming the internal mechanism. 'Interact through function calls and decorators' "
        "preserves ambiguity about where the shared state lives. "
        "CAUSAL AMBIGUITY: (1) module-level variable, (2) mutable default parameter, "
        "(3) closure variable in decorator, (4) shared queue state. "
        "DIFFICULTY: C — three files, mechanism ambiguity preserved.",
}

# ── use_before_set_c: "from a previous call" hints mechanism ──
F["use_before_set_c"] = {
    "enriched_task_prompt":
        "A search function returns unexpected results when no items match the current criteria — "
        "it returns data that does not correspond to the current input. The system involves "
        "pipeline.py, loader.py, and validator.py. Fix the implementation so that no-match "
        "cases return None.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'results from a previous call' directly names cross-call leakage. "
        "FIX: 'data that does not correspond to the current input' describes the output "
        "mismatch without attributing it to prior calls. "
        "CAUSAL AMBIGUITY: (1) pipeline retains a stale variable, (2) loader caches results, "
        "(3) validator returns wrong data on edge cases. "
        "DIFFICULTY: C — three files, no temporal hint. V3 prompt already good. "
        "CAUSAL AMBIGUITY: three files create three plausible state locations — "
        "(1) pipeline.py retains a stale result variable, (2) loader.py caches results "
        "across calls, (3) validator.py filters incorrectly returning old data. The model "
        "must trace the no-match path through all three.",
}

# ── stale_cache_c: "cache layers" / "caching layers" is directional ──
F["stale_cache_c"] = {
    "enriched_task_prompt":
        "The API returns outdated product data after updates, even though some data access paths "
        "appear to be correctly updated. The system uses catalog.py, cache.py, and api.py with "
        "multiple data access paths. Fix the implementation so that updates are visible to "
        "all read paths.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'cache layers' and 'caching layers' directly name the architecture as a "
        "cache problem, nudging toward cache invalidation as the fix. "
        "FIX: replaced with 'data access paths' — neutral terminology that could refer to "
        "caching, direct DB reads, API-level aggregation, or in-memory stores. "
        "CAUSAL AMBIGUITY: (1) cache not invalidated, (2) wrong cache layer invalidated, "
        "(3) API-level read path bypasses updates, (4) DB write not committed. "
        "'Some data access paths appear to be correctly updated' hints at partial correctness "
        "without naming caching specifically. "
        "DIFFICULTY: C — three files, neutral architecture language.",
}

# ── temporal_drift_c: "transformation stages" is directional ──
F["temporal_drift_c"] = {
    "enriched_task_prompt":
        "The report shows incorrect raw metrics — values that should be in the hundreds appear "
        "as approximately 1.0. The system involves pipeline.py, transforms.py, and metrics.py, "
        "with data flowing through multiple processing steps before metrics are computed. "
        "Fix the data flow so that raw metrics reflect the original input.",

    "enriched_task_prompt_justification":
        "V4 ISSUE: 'transformation stages' directly names the architecture, nudging toward "
        "a temporal ordering / transform-before-compute diagnosis. "
        "FIX: replaced with 'processing steps' — neutral terminology that could refer to "
        "normalization, filtering, aggregation, or routing. "
        "CAUSAL AMBIGUITY: (1) metrics computed on wrong-stage data, (2) processing step "
        "corrupts values, (3) metrics function normalizes internally, (4) data flow routing "
        "sends wrong input to metrics. "
        "DIFFICULTY: C — three files, neutral processing language.",
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

    print(f"Total: {total}, Refined: {fixed}, Unchanged: {total - fixed}")


if __name__ == "__main__":
    main()
