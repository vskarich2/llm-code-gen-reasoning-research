"""Stage 1: Oracle evaluation with massive parallelism."""

import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def is_unjudgable(root_cause, fix_strategy):
    """Pre-filter: skip API call if reasoning missing."""
    rc = (root_cause or "").strip()
    fs = (fix_strategy or "").strip()
    if not rc and not fs:
        return True
    return len(rc) + len(fs) < 20


def _eval_single(event, cases_by_id, config, prompt_variant="a"):
    """Evaluate one event. Returns result dict."""
    from core.evaluation.oracle_eval.reasoning_truth import (
        build_oracle_spec, load_buggy_code, render_prompt,
        parse_response)
    from core.pipeline import call_model

    cid = event["case_id"]
    case = cases_by_id.get(cid)
    if not case:
        return _make_label(event, "UNJUDGABLE", "", "case_not_found")

    rc = event.get("root_cause", "")
    fs = event.get("fix_strategy", "")
    if is_unjudgable(rc, fs):
        return _make_label(event, "UNJUDGABLE", "", "pre_filter")

    oracle = build_oracle_spec(case)
    buggy = load_buggy_code(case, PROJECT_ROOT)

    # Select prompt template
    if prompt_variant == "b":
        import jinja2
        tmpl_path = (Path(PROJECT_ROOT) / "oracle_eval"
                     / "reasoning_truth_prompt_b.j2")
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tmpl_path.parent)),
            undefined=jinja2.StrictUndefined)
        tmpl = env.get_template(tmpl_path.name)
        prompt = tmpl.render(
            task=oracle["task"], buggy_code=buggy,
            bug_type=oracle["bug_type"],
            bug_location=oracle["bug_location"],
            invariant=oracle["invariant"],
            fix_pattern=oracle["fix_pattern"],
            mechanism_description=oracle["mechanism_description"],
            trap_description=oracle["trap_description"],
            root_cause=rc or "[MISSING]",
            fix_strategy=fs or "[MISSING]")
    else:
        prompt = render_prompt(oracle, rc, fs, buggy)

    t0 = time.monotonic()
    try:
        cr = call_model(
            prompt, model=config.models.evaluator.name,
            raw=True, logger=None, phase="oracle_eval")
        raw_resp = cr.response
    except Exception as e:
        return _make_label(
            event, "UNJUDGABLE", "", f"call_error:{e!s:.80}")
    elapsed = int((time.monotonic() - t0) * 1000)

    label, justification, err = parse_response(raw_resp)
    return _make_label(
        event, label, justification, err,
        raw_resp=raw_resp, latency_ms=elapsed,
        prompt_hash=hashlib.sha256(
            prompt.encode()).hexdigest()[:16])


def _make_label(event, label, justification, error,
                raw_resp="", latency_ms=0, prompt_hash=""):
    return {
        "case_id": event["case_id"],
        "model": event["model"],
        "condition": event["condition"],
        "trial": event["trial"],
        "reasoning_truth": label,
        "justification": justification,
        "parse_error": error,
        "response_raw": raw_resp,
        "latency_ms": latency_ms,
        "prompt_hash": prompt_hash,
    }


def _event_key(e):
    return (e["case_id"], e["model"], e["trial"], e["condition"])


def load_existing_labels(output_dir):
    """Load already-computed labels for resume."""
    lf = Path(output_dir) / "oracle_labels.jsonl"
    existing = {}
    if lf.exists():
        for line in open(lf):
            try:
                r = json.loads(line)
                k = (r["case_id"], r["model"],
                     r["trial"], r["condition"])
                existing[k] = r
            except (json.JSONDecodeError, KeyError):
                continue
    return existing


def run_stage_1(events, cases_by_id, config, output_dir,
                n_workers=200, prompt_variant="a"):
    """Run oracle eval with thread-pool parallelism."""
    from core.config.experiment_config import get_config
    cfg = config or get_config()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    labels_file = out / "oracle_labels.jsonl"

    # Resume: load existing labels
    existing = load_existing_labels(output_dir)
    to_eval = [e for e in events if _event_key(e) not in existing]
    skip_unjudgable = [e for e in to_eval if is_unjudgable(
        e.get("root_cause", ""), e.get("fix_strategy", ""))]
    to_call = [e for e in to_eval if not is_unjudgable(
        e.get("root_cause", ""), e.get("fix_strategy", ""))]

    print(f"  Stage 1: {len(events)} total, {len(existing)} cached, "
          f"{len(skip_unjudgable)} pre-filter UNJUDGABLE, "
          f"{len(to_call)} to evaluate", flush=True)

    # Write UNJUDGABLE pre-filters immediately
    with open(labels_file, "a") as f:
        for e in skip_unjudgable:
            r = _make_label(e, "UNJUDGABLE", "", "pre_filter")
            f.write(json.dumps(r) + "\n")
            existing[_event_key(e)] = r

    if not to_call:
        print("  All events already labeled", flush=True)
        return existing

    # Thread-pool parallel evaluation
    completed = 0
    total = len(to_call)
    print(f"  Evaluating {total} events with {n_workers} workers...",
          flush=True)

    with open(labels_file, "a") as f:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    _eval_single, e, cases_by_id, cfg, prompt_variant
                ): e for e in to_call
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    e = futures[future]
                    result = _make_label(
                        e, "UNJUDGABLE", "",
                        f"future_error:{exc!s:.80}")

                f.write(json.dumps(result) + "\n")
                f.flush()
                existing[_event_key(futures[future])] = result
                completed += 1

                if completed % 100 == 0 or completed == total:
                    label = result["reasoning_truth"]
                    print(
                        f"  [{completed:6d}/{total}] "
                        f"{result['case_id'][:20]:20s} "
                        f"{result['model'][:18]:18s} → {label}",
                        flush=True)

    print(f"  Stage 1 complete: {len(existing)} labels", flush=True)
    return existing
