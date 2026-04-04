"""Report generation. LLM summary from structured case_data + hardcoded disclaimers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from llm_client import LLMCallError, call_llm
from schemas import AggregationResult

_log = logging.getLogger("reddit_med_signal.report")

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "summarization.txt"

DISCLAIMER_HEADER = """> **IMPORTANT: This report is NOT medical advice.**
> It summarizes anecdotal reports from Reddit users. It has NOT been verified
> by medical professionals. Mention counts are NOT prevalence estimates.
> Correlation is NOT causation. Do NOT use this to make treatment decisions.
> Consult qualified medical professionals for any medical questions.
"""

DISCLAIMER_FOOTER = """---
*This report was auto-generated from Reddit posts and comments. It reflects
what anonymous internet users have written, not clinical evidence. Counts
reflect how many Reddit posts/comments mentioned an effect, not how common
the effect actually is. Many reported effects may be coincidental,
misattributed, or fabricated. This tool is for background situational
awareness only.*
"""


def _build_reliability_section(result: AggregationResult) -> str:
    """Build the mandatory Data Reliability section. Deterministic, no LLM."""
    total_firsthand = (
        result.total_firsthand_high
        + result.total_firsthand_medium
        + result.total_firsthand_low
    )

    lines = [
        "## Data Reliability",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Items retrieved (posts + comments) | {result.total_raw_items} |",
        f"| Items dropped by heuristic filter | "
        f"{result.total_raw_items - result.total_after_heuristic_filter} |",
        f"| Items sent to extraction | {result.total_extraction_attempted} |",
        f"| Extraction successes | {result.total_extraction_succeeded} |",
        f"| Extraction failures | {result.total_extraction_failed} |",
        f"| Classified firsthand (high confidence) | {result.total_firsthand_high} |",
        f"| Classified firsthand (medium confidence) | {result.total_firsthand_medium} |",
        f"| Classified firsthand (low confidence) | {result.total_firsthand_low} |",
        f"| Excluded (non-firsthand) | {result.total_excluded} |",
        f"| Near-duplicates removed | {result.total_deduped} |",
        f"| Ungrounded effects dropped | {result.ungrounded_effects_dropped} |",
        f"| **Records used in aggregation** | **{total_firsthand}** |",
        "",
    ]

    # Sparse case_data warning
    if result.is_sparse:
        lines.append(
            f"**Sparse case_data warning:** Only {total_firsthand} firsthand "
            f"reports found. Interpret with extreme caution."
        )
    else:
        lines.append(
            f"**Data adequacy:** {total_firsthand} firsthand reports — adequate."
        )
    lines.append("")

    # Unmapped labels
    if result.unmapped_labels:
        lines.append("**Unmapped effect labels** (not in synonym map, used as-is):")
        for label in result.unmapped_labels:
            # Count occurrences
            count = 0
            for theme in result.themes:
                if theme.effect_normalized == label:
                    count = theme.mention_count
                    break
            lines.append(f"- `{label}` ({count} mentions)")
        lines.append("")
        lines.append(
            "*Consider adding these to `config/effect_synonyms.yaml` "
            "for better aggregation in future runs.*"
        )
        lines.append("")

    return "\n".join(lines)


def _build_skepticism_section(result: AggregationResult) -> str:
    """Build the When to Be Skeptical section. Deterministic."""
    total_firsthand = (
        result.total_firsthand_high
        + result.total_firsthand_medium
        + result.total_firsthand_low
    )
    warnings: list[str] = []

    # Low sample size
    if total_firsthand < 10:
        warnings.append(
            "- **Very few firsthand reports** — fewer than 10 experience "
            "reports were found. Any patterns may be noise."
        )
    elif total_firsthand < 25:
        warnings.append(
            "- **Small sample** — fewer than 25 firsthand reports. "
            "Patterns are suggestive but not robust."
        )

    # High disagreement
    if result.conflicts:
        direct = sum(
            1 for c in result.conflicts
            if c.conflict_type.value == "direct_contradiction"
        )
        if direct > 0:
            warnings.append(
                f"- **Direct contradictions present** — {direct} effect pair(s) "
                f"show directly opposing reports with no clear explanation."
            )

    # High low-confidence fraction
    if total_firsthand > 0:
        low_frac = result.total_firsthand_low / total_firsthand
        if low_frac > 0.3:
            warnings.append(
                f"- **High uncertainty** — {result.total_firsthand_low} of "
                f"{total_firsthand} records ({low_frac:.0%}) have low "
                f"firsthand confidence."
            )

    # Many unmapped labels
    if len(result.unmapped_labels) > 5:
        warnings.append(
            f"- **Many unmapped effect labels** — {len(result.unmapped_labels)} "
            f"effect labels were not in the synonym map. Some effects may be "
            f"fragmented across slightly different labels."
        )

    # Extraction failures
    if result.total_extraction_failed > 0:
        fail_rate = result.total_extraction_failed / max(
            result.total_extraction_attempted, 1
        )
        if fail_rate > 0.1:
            warnings.append(
                f"- **Extraction failures** — {result.total_extraction_failed} "
                f"items ({fail_rate:.0%}) failed extraction. Some case_data was lost."
            )

    if not warnings:
        return ""

    lines = ["## When to Be Skeptical", ""]
    lines.extend(warnings)
    lines.append("")
    return "\n".join(lines)


def _prepare_summary_input(result: AggregationResult, max_tokens: int) -> str:
    """Serialize AggregationResult for the summary LLM call.

    Truncates if needed to stay under max_tokens (approximate).
    """
    # Build a focused JSON with only what the LLM needs
    summary_data = {
        "drug_query": result.drug_query,
        "canonical_drug_name": result.canonical_drug_name,
        "total_firsthand_reports": (
            result.total_firsthand_high
            + result.total_firsthand_medium
            + result.total_firsthand_low
        ),
        "is_sparse": result.is_sparse,
        "themes": [],
        "conflicts": [],
        "co_medication_counts": result.co_medication_counts,
        "uncertainty_summary": result.uncertainty_summary,
    }

    # Add themes (truncate to top 20 if needed)
    for theme in result.themes[:20]:
        theme_data = {
            "effect": theme.effect_normalized,
            "mentions": theme.mention_count,
            "weighted_mentions": theme.weighted_count,
            "directionality": theme.directionality_breakdown,
            "severity": theme.severity_breakdown,
            "secondorder_chains": theme.secondorder_chains,
            "example_excerpts": theme.example_excerpts[:2],
        }
        summary_data["themes"].append(theme_data)

    # Add conflicts
    for conflict in result.conflicts:
        summary_data["conflicts"].append({
            "effect_a": conflict.effect_a,
            "effect_b": conflict.effect_b,
            "type": conflict.conflict_type.value,
            "summary": conflict.evidence_summary,
            "count_a": conflict.count_a,
            "count_b": conflict.count_b,
            "example_a": conflict.example_a[:150],
            "example_b": conflict.example_b[:150],
        })

    text = json.dumps(summary_data, indent=2)

    # Rough token estimate (1 token ≈ 4 chars)
    est_tokens = len(text) // 4
    if est_tokens > max_tokens:
        _log.warning(
            "Summary input too large (%d est tokens, max %d); truncating themes",
            est_tokens, max_tokens,
        )
        # Reduce themes and examples
        summary_data["themes"] = summary_data["themes"][:15]
        for t in summary_data["themes"]:
            t["example_excerpts"] = t["example_excerpts"][:1]
        text = json.dumps(summary_data, indent=2)

    return text


def generate_report(
    result: AggregationResult,
    cfg: dict,
) -> str:
    """Generate the full Markdown report.

    Returns the complete report string.
    """
    summary_cfg = cfg.get("summary", {})
    model = summary_cfg.get("model", "gpt-4.1-mini")
    temperature = summary_cfg.get("temperature", 0.3)
    max_tokens = summary_cfg.get("max_tokens", 2048)
    timeout = summary_cfg.get("timeout_seconds", 60)
    max_input = summary_cfg.get("max_summary_input_tokens", 8000)

    # Load prompt template
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Summary prompt not found: {_PROMPT_PATH}")
    prompt_template = _PROMPT_PATH.read_text()

    # Prepare input
    aggregation_json = _prepare_summary_input(result, max_input)
    prompt = prompt_template.replace("{aggregation_json}", aggregation_json)

    # Call LLM for prose summary
    try:
        llm_summary = call_llm(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    except LLMCallError as e:
        _log.error("Summary generation failed: %s", e)
        llm_summary = (
            "## Summary\n\n"
            "*Summary generation failed. See the case_data sections below "
            "for raw aggregated information.*\n"
        )

    # Build deterministic sections
    reliability = _build_reliability_section(result)
    skepticism = _build_skepticism_section(result)

    # Metadata footer
    total_fh = (
        result.total_firsthand_high
        + result.total_firsthand_medium
        + result.total_firsthand_low
    )
    meta = (
        f"<!-- Run: {result.run_timestamp} | "
        f"Items: {result.total_raw_items} raw, "
        f"{result.total_after_heuristic_filter} filtered, "
        f"{total_fh} firsthand, "
        f"{result.total_extraction_failed} failed -->"
    )

    # Assemble report
    parts = [
        DISCLAIMER_HEADER,
        "",
        f"# {result.canonical_drug_name.title()} — Anecdotal Reddit Report",
        "",
        f"**Generated:** {result.run_timestamp}",
        f"**Query:** {result.drug_query}",
        f"**Firsthand reports:** {total_fh}",
        "",
        llm_summary,
        "",
        reliability,
        skepticism,
        DISCLAIMER_FOOTER,
        "",
        meta,
    ]

    report = "\n".join(parts)
    return report
