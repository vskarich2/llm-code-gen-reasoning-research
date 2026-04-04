"""CLI entry point for reddit_med_signal."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from aggregation import aggregate, deduplicate_records
from config import get_data_dir, get_reports_dir, get_reddit_credentials, load_config
from drug_aliases import load_alias_map, resolve_aliases
from extraction import extract_batch
from filtering import apply_heuristic_filters
from normalization import load_synonym_map, normalize_records
from report import generate_report
from retrieval import retrieve
from schemas import ExtractedRecord, RawItem


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[reddit_med_signal] %(message)s",
        stream=sys.stderr,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _save_jsonl(items: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def _load_raw_cache(path: Path) -> list[RawItem]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(RawItem.model_validate_json(line))
    return items


def _load_extracted_cache(path: Path) -> list[ExtractedRecord]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(ExtractedRecord.model_validate_json(line))
    return records


def _estimate_cost(num_extraction_calls: int, cfg: dict) -> float:
    budget = cfg.get("budget", {})
    # Rough estimate: ~500 input tokens, ~300 output tokens per extraction
    ext_input = num_extraction_calls * 500
    ext_output = num_extraction_calls * 300
    ext_cost = (
        (ext_input / 1_000_000) * budget.get("nano_input_per_million", 0.10)
        + (ext_output / 1_000_000) * budget.get("nano_output_per_million", 0.40)
    )
    # Summary: ~3000 input, ~1000 output
    sum_cost = (
        (3000 / 1_000_000) * budget.get("mini_input_per_million", 0.40)
        + (1000 / 1_000_000) * budget.get("mini_output_per_million", 1.60)
    )
    return ext_cost + sum_cost


@click.command()
@click.argument("drug_name")
@click.option("--config", "config_path", default=None, help="Path to config YAML")
@click.option("--subreddits", default=None, help="Comma-separated subreddit override")
@click.option("--max-items", default=None, type=int, help="Override total_raw_item_cap")
@click.option("--from-cache", "cache_ts", default=None, help="Reuse extracted cache by timestamp")
@click.option("--from-raw-cache", "raw_cache_ts", default=None, help="Reuse raw cache by timestamp")
@click.option("--force", is_flag=True, help="Skip cost confirmation")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
def main(
    drug_name: str,
    config_path: str | None,
    subreddits: str | None,
    max_items: int | None,
    cache_ts: str | None,
    raw_cache_ts: str | None,
    force: bool,
    verbose: bool,
) -> None:
    """Gather and summarize anecdotal Reddit reports about a medication."""
    _setup_logging(verbose)
    log = logging.getLogger("reddit_med_signal.cli")

    click.echo(
        "[reddit_med_signal] This tool provides anecdotal summaries "
        "from Reddit. Not medical advice."
    )

    # Load config
    cfg = load_config(config_path)

    # Subreddit override
    if subreddits:
        cfg["subreddits"] = [s.strip() for s in subreddits.split(",")]

    # Max items override
    if max_items is not None:
        cfg.setdefault("retrieval", {})["total_raw_item_cap"] = max_items

    ts = cache_ts or raw_cache_ts or _timestamp()
    data_dir = get_data_dir()
    reports_dir = get_reports_dir()
    canonical = drug_name.lower().strip()

    # Step 1: Query expansion
    alias_map = load_alias_map()
    aliases = resolve_aliases(drug_name, alias_map)
    canonical_name = aliases[0]
    click.echo(f"[1/7] Aliases: {canonical_name} → {aliases}")

    # Step 2: Retrieval (or cache)
    raw_path = data_dir / "raw" / f"{canonical_name}_{ts}.jsonl"
    extracted_path = data_dir / "extracted" / f"{canonical_name}_{ts}.jsonl"

    if cache_ts:
        # Skip retrieval AND extraction — load extracted cache
        click.echo(f"[2/7] Loading extracted cache: {extracted_path}")
        if not extracted_path.exists():
            click.echo(f"ERROR: Cache not found: {extracted_path}", err=True)
            sys.exit(1)
        records = _load_extracted_cache(extracted_path)
        raw_count = 0
        filtered_count = 0
        ext_attempted = len(records)
        ext_succeeded = len(records)
        ext_failed = 0
        click.echo(f"       Loaded {len(records)} cached records")
    else:
        if raw_cache_ts:
            # Load raw cache, skip retrieval
            click.echo(f"[2/7] Loading raw cache: {raw_path}")
            if not raw_path.exists():
                click.echo(f"ERROR: Raw cache not found: {raw_path}", err=True)
                sys.exit(1)
            raw_items = _load_raw_cache(raw_path)
        else:
            # Fresh retrieval
            click.echo(
                f"[2/7] Retrieving from {len(cfg.get('subreddits', []))} "
                f"subreddits (cap: "
                f"{cfg.get('retrieval', {}).get('total_raw_item_cap', 500)})..."
            )
            credentials = get_reddit_credentials()
            raw_items = retrieve(aliases, cfg.get("subreddits", []), cfg, credentials)
            _save_jsonl(raw_items, raw_path)
            click.echo(f"       Cached: {raw_path}")

        raw_count = len(raw_items)
        post_count = sum(1 for i in raw_items if i.item_type == "post")
        comment_count = raw_count - post_count
        click.echo(
            f"       Found {raw_count} items ({post_count} posts, "
            f"{comment_count} comments)"
        )

        # Step 3: Heuristic filtering
        filtered = apply_heuristic_filters(raw_items, cfg)
        filtered_count = len(filtered)
        click.echo(
            f"[3/7] Heuristic filter: {raw_count} → {filtered_count} items"
        )

        # Cost check
        est_cost = _estimate_cost(filtered_count, cfg)
        max_cost = cfg.get("budget", {}).get("max_cost_estimate_usd", 0.50)
        if est_cost > max_cost and not force:
            click.echo(
                f"WARNING: Estimated cost ${est_cost:.2f} exceeds "
                f"limit ${max_cost:.2f}. Use --force to proceed.",
                err=True,
            )
            sys.exit(1)

        # Step 4: Extraction
        click.echo(
            f"[4/7] Extracting structured effects ({filtered_count} LLM calls)..."
        )
        records, ext_succeeded, ext_failed = extract_batch(
            filtered, drug_name, canonical_name, aliases, cfg,
        )
        ext_attempted = ext_succeeded + ext_failed

        # Cache extracted records
        _save_jsonl(records, extracted_path)
        click.echo(f"       Cached: {extracted_path}")

        fh_high = sum(
            1 for r in records
            if r.firsthand_final and r.firsthand_final_confidence == "high"
        )
        fh_med = sum(
            1 for r in records
            if r.firsthand_final and r.firsthand_final_confidence == "medium"
        )
        fh_low = sum(
            1 for r in records
            if r.firsthand_final and r.firsthand_final_confidence == "low"
        )
        click.echo(
            f"       Firsthand: {fh_high} high, {fh_med} medium, {fh_low} low"
        )
        if ext_failed > 0:
            click.echo(f"       Extraction failures: {ext_failed}")

    # Step 5: Normalization
    synonym_map = load_synonym_map()
    records, unmapped = normalize_records(records, synonym_map)
    total_effects = sum(len(r.reported_effects) for r in records)
    click.echo(
        f"[5/7] Normalization: {total_effects} effects → "
        f"{len(unmapped)} unmapped labels"
    )

    # Step 6: Deduplication + Aggregation
    firsthand_records = [r for r in records if r.firsthand_final]
    deduped, dedup_removed = deduplicate_records(firsthand_records)
    # Replace firsthand records in full list (keep non-firsthand for counting)
    non_firsthand = [r for r in records if not r.firsthand_final]
    all_for_agg = deduped + non_firsthand

    # Count ungrounded
    ungrounded = 0
    for r in records:
        for flag in r.uncertainty_flags:
            if flag.startswith("ungrounded_effects_dropped:"):
                try:
                    ungrounded += int(flag.split(":")[1])
                except (ValueError, IndexError):
                    pass

    result = aggregate(
        records=all_for_agg,
        drug_query=drug_name,
        canonical_name=canonical_name,
        unmapped_labels=unmapped,
        cfg=cfg,
        raw_count=raw_count if not cache_ts else 0,
        filtered_count=filtered_count if not cache_ts else 0,
        extraction_attempted=ext_attempted,
        extraction_succeeded=ext_succeeded,
        extraction_failed=ext_failed,
        dedup_removed=dedup_removed,
        ungrounded_dropped=ungrounded,
        run_timestamp=ts,
    )
    click.echo(
        f"[6/7] Aggregation: {len(result.themes)} themes, "
        f"{len(result.conflicts)} conflicts"
    )

    # Step 7: Report generation
    click.echo("[7/7] Generating report...")
    report_text = generate_report(result, cfg)

    report_path = reports_dir / f"{canonical_name}_{ts}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text)
    click.echo(f"       Report: {report_path}")

    # Cost summary
    if not cache_ts:
        est_cost = _estimate_cost(ext_attempted, cfg)
        click.echo(f"\nCost: ~${est_cost:.2f}")

    click.echo("Done.")
