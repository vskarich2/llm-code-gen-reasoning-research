"""Stage 0: Extract, deduplicate, and verify matched triples."""

import json
import hashlib
from collections import defaultdict
from pathlib import Path

CANONICAL_PRIORITY = [
    "logs/v2_targeted_50trial_canonical",
    "logs/v2_full_4model_10trial_canonical",
    "logs/v2_targeted_50trial_tranche2",
    "logs/v2_targeted_50trial_tranche3",
    "logs/v2_targeted_50trial_tranche4",
    "logs/v2_anthropic_50trial_v2",
    "logs/v2_anthropic_50trial_v3",
    "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_sonnet46_v2",
    "logs/v2_gpt5_50trial",
    "logs/v2_gpt5_50trial_v2",
    "logs/v2_anthropic_haiku45",
]

REQUIRED_CONDITIONS = frozenset({
    "baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"
})


def _source_priority(source):
    """Lower = higher priority."""
    for i, p in enumerate(CANONICAL_PRIORITY):
        if source.endswith(p) or p in source:
            return i
    return len(CANONICAL_PRIORITY)


def load_all_events(log_dirs):
    """Load all case.end events from merged_events.jsonl files."""
    events = []
    for ld in log_dirs:
        merged = Path(ld) / "merged_events.jsonl"
        if not merged.exists():
            print(f"  WARN: {merged} not found", flush=True)
            continue
        for line in open(merged):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "case.end":
                continue
            p = ev.get("payload", {})
            art = p.get("v2_artifact", {})
            events.append({
                "case_id": ev.get("case_id"),
                "model": ev.get("model"),
                "condition": ev.get("condition"),
                "trial": ev.get("trial"),
                "root_cause": art.get("raw_root_cause", ""),
                "fix_strategy": art.get("raw_fix_strategy", ""),
                "parse_status": art.get("parse_status", ""),
                "execution_pass": p.get("pass", False),
                "reconstruction_status": p.get(
                    "reconstruction_status", ""),
                "old_mc": p.get("mechanism_correct"),
                "source": str(ld),
                "timestamp": ev.get("timestamp", ""),
            })
    return events


def deduplicate(events, output_dir):
    """Deduplicate events. Returns deduped list. Writes audit logs."""
    by_key = defaultdict(list)
    for e in events:
        k = (e["case_id"], e["model"], e["trial"], e["condition"])
        by_key[k].append(e)

    deduped = []
    duplicates = []
    excluded_keys = set()
    excluded_details = []

    for key, evts in by_key.items():
        if len(evts) == 1:
            deduped.append(evts[0])
            continue

        # Log all duplicates
        for e in evts:
            duplicates.append({
                "key": list(key), "source": e["source"],
                "execution_pass": e["execution_pass"],
                "reconstruction_status": e["reconstruction_status"],
                "timestamp": e["timestamp"],
            })

        # Check execution_pass consistency
        passes = set(e["execution_pass"] for e in evts)
        if len(passes) > 1:
            excluded_keys.add(key)
            excluded_details.append({
                "key": list(key),
                "reason": "execution_pass_disagreement",
                "values": [
                    {"source": e["source"],
                     "pass": e["execution_pass"]}
                    for e in evts],
            })
            continue

        # Pick by priority: canonical order, then timestamp
        evts.sort(key=lambda e: (
            _source_priority(e["source"]), e["timestamp"]))
        deduped.append(evts[0])

    # Write audit logs
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if duplicates:
        with open(out / "duplicates_log.jsonl", "w") as f:
            for d in duplicates:
                f.write(json.dumps(d) + "\n")
    if excluded_details:
        (out / "excluded_triples.json").write_text(
            json.dumps(excluded_details, indent=2))

    print(f"  Dedup: {len(events)} → {len(deduped)} events "
          f"({len(duplicates)} duplicate entries, "
          f"{len(excluded_keys)} triples excluded for "
          f"inconsistency)", flush=True)

    # Remove events belonging to excluded triples
    result = []
    for e in deduped:
        k = (e["case_id"], e["model"], e["trial"], e["condition"])
        if k not in excluded_keys:
            result.append(e)
    return result


def identify_matched_triples(events):
    """Keep only events in complete matched triples."""
    by_triple = defaultdict(dict)
    for e in events:
        tk = (e["case_id"], e["model"], e["trial"])
        by_triple[tk][e["condition"]] = e

    matched = []
    for tk, conds in by_triple.items():
        if REQUIRED_CONDITIONS.issubset(conds.keys()):
            for c in REQUIRED_CONDITIONS:
                matched.append(conds[c])

    return matched


def verify_matched_triples(events):
    """Assert integrity: exactly 1 event per (triple, condition)."""
    from collections import Counter
    keys = [(e["case_id"], e["model"], e["trial"], e["condition"])
            for e in events]
    counts = Counter(keys)
    dups = {k: v for k, v in counts.items() if v > 1}
    if dups:
        raise RuntimeError(
            f"Matched triple integrity violation: "
            f"{len(dups)} keys with >1 event: "
            f"{list(dups.keys())[:3]}")
    n_triples = len(events) // 3
    assert len(events) == n_triples * 3, (
        f"Event count {len(events)} not divisible by 3")
    print(f"  Verified: {n_triples} matched triples, "
          f"{len(events)} events", flush=True)


def run_stage_0(log_dirs, output_dir):
    """Extract, deduplicate, identify matched triples."""
    print("Stage 0: Extract and deduplicate", flush=True)
    events = load_all_events(log_dirs)
    print(f"  Loaded {len(events)} case.end events", flush=True)

    events = deduplicate(events, output_dir)
    matched = identify_matched_triples(events)
    verify_matched_triples(matched)

    out = Path(output_dir) / "matched_events.jsonl"
    with open(out, "w") as f:
        for e in matched:
            f.write(json.dumps(e) + "\n")
    print(f"  Wrote {len(matched)} events to {out}", flush=True)
    return matched
