"""Grounded LLM extraction with evidence spans. One call per item."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from firsthand import compute_firsthand_signals, resolve_firsthand
from llm_client import LLMCallError, call_llm
from schemas import ExtractedRecord, FirsthandSignals, RawItem, ReportedEffect

_log = logging.getLogger("reddit_med_signal.extraction")

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "extraction.txt"

_EXTRACTION_SCHEMA = """{
  "firsthand_llm": true/false,
  "firsthand_llm_confidence": "high" | "medium" | "low",
  "mentions_personal_use": true/false,
  "reported_effects": [
    {
      "effect_raw": "short label",
      "effect_evidence_span": "EXACT substring from source text",
      "directionality": "positive" | "negative" | "neutral" | "ambiguous",
      "severity_hint": "mild" | "moderate" | "severe" | "unspecified",
      "is_secondorder": true/false,
      "secondorder_chain": "effect_a → effect_b" or null,
      "temporal_context": "after 2 weeks" or null,
      "extraction_confidence": "high" | "medium" | "low"
    }
  ],
  "co_medications": ["drug_name", ...],
  "temporal_info": "summary string" or null,
  "uncertainty_flags": ["speculative", "secondhand", ...],
  "extraction_notes": "string" or null
}"""


def _load_prompt_template() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Extraction prompt not found: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text()


def _validate_grounding(span: str, source_text: str) -> bool:
    """Check that evidence span is present in source text.

    Uses exact substring match first, then contiguous token overlap.
    NOT bag-of-words — checks token sequence.
    """
    span_clean = span.lower().strip()
    if not span_clean:
        return False
    text_clean = source_text.lower()

    # Exact substring match
    if span_clean in text_clean:
        return True

    # Contiguous token overlap: find longest common token subsequence
    # Check that >= 80% of span tokens appear as a contiguous run in text
    span_tokens = span_clean.split()
    text_tokens = text_clean.split()
    if not span_tokens:
        return False

    # Sliding window: find best contiguous match
    best_match = 0
    window_size = len(span_tokens)
    for i in range(len(text_tokens) - window_size + 1):
        window = text_tokens[i:i + window_size]
        matches = sum(1 for s, t in zip(span_tokens, window) if s == t)
        best_match = max(best_match, matches)

    # Also check with smaller windows (span might be slightly shorter/longer)
    for offset in range(-2, 3):
        ws = window_size + offset
        if ws < 3 or ws > len(text_tokens):
            continue
        for i in range(len(text_tokens) - ws + 1):
            window = text_tokens[i:i + ws]
            # Compare overlap of span tokens with this window
            overlap = len(set(span_tokens) & set(window))
            best_match = max(best_match, overlap)

    threshold = 0.8
    return (best_match / len(span_tokens)) >= threshold


def _parse_llm_response(
    raw_json: str,
    item: RawItem,
    heuristic: FirsthandSignals,
    drug_query: str,
    canonical_name: str,
) -> ExtractedRecord | None:
    """Parse LLM JSON response into ExtractedRecord.

    Validates grounding for each effect. Drops ungrounded effects.
    Returns None only if JSON parsing fails entirely.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        _log.error("JSON parse error for %s: %s", item.reddit_id, e)
        return None

    # Resolve firsthand via decision table
    llm_fh = data.get("firsthand_llm", False)
    llm_conf = data.get("firsthand_llm_confidence", "low")
    final_fh, final_conf = resolve_firsthand(
        heuristic.heuristic_firsthand_score, llm_fh, llm_conf,
    )

    # Parse and validate effects
    grounded_effects: list[ReportedEffect] = []
    ungrounded_count = 0
    raw_effects = data.get("reported_effects", [])

    for eff_data in raw_effects:
        try:
            effect = ReportedEffect(
                effect_raw=eff_data.get("effect_raw", ""),
                effect_evidence_span=eff_data.get("effect_evidence_span", ""),
                directionality=eff_data.get("directionality", "ambiguous"),
                severity_hint=eff_data.get("severity_hint", "unspecified"),
                is_secondorder=eff_data.get("is_secondorder", False),
                secondorder_chain=eff_data.get("secondorder_chain"),
                temporal_context=eff_data.get("temporal_context"),
                extraction_confidence=eff_data.get("extraction_confidence", "low"),
            )
        except (ValidationError, Exception) as e:
            _log.warning(
                "Effect parse error for %s: %s", item.reddit_id, e
            )
            continue

        # Validate grounding
        if not effect.effect_evidence_span.strip():
            _log.debug(
                "Empty evidence span for effect '%s' in %s — dropping",
                effect.effect_raw, item.reddit_id,
            )
            ungrounded_count += 1
            continue

        if not _validate_grounding(effect.effect_evidence_span, item.body):
            _log.debug(
                "Ungrounded effect '%s' in %s — span not in source text",
                effect.effect_raw, item.reddit_id,
            )
            ungrounded_count += 1
            continue

        grounded_effects.append(effect)

    # Build uncertainty flags
    flags = list(data.get("uncertainty_flags", []))
    if ungrounded_count > 0:
        flags.append(f"ungrounded_effects_dropped:{ungrounded_count}")

    record = ExtractedRecord(
        drug_query=drug_query,
        canonical_drug_name=canonical_name,
        source_type=item.item_type,
        subreddit=item.subreddit,
        reddit_id=item.reddit_id,
        url=item.url,
        authored_timestamp=item.created_utc,
        text_excerpt=item.body[:800],
        comment_depth=item.comment_depth,
        firsthand_heuristic=heuristic,
        firsthand_llm=llm_fh,
        firsthand_llm_confidence=llm_conf,
        firsthand_final=final_fh,
        firsthand_final_confidence=final_conf,
        mentions_personal_use=data.get("mentions_personal_use", False),
        reported_effects=grounded_effects,
        co_medications=data.get("co_medications", []),
        temporal_info=data.get("temporal_info"),
        uncertainty_flags=flags,
        extraction_notes=data.get("extraction_notes"),
    )
    return record


def extract_batch(
    items: list[RawItem],
    drug_query: str,
    canonical_name: str,
    aliases: list[str],
    cfg: dict,
) -> tuple[list[ExtractedRecord], int, int]:
    """Run grounded extraction on all items.

    Returns (records, success_count, failure_count).
    Respects max_extraction_calls cap. Prioritizes by heuristic score.
    """
    ext_cfg = cfg.get("extraction", {})
    max_calls = ext_cfg.get("max_extraction_calls", 350)
    model = ext_cfg.get("model", "gpt-4.1-nano")
    temperature = ext_cfg.get("temperature", 0.0)
    max_tokens = ext_cfg.get("max_tokens", 1024)
    timeout = ext_cfg.get("timeout_seconds", 30)
    max_retries = ext_cfg.get("max_retries", 3)
    retry_delay = ext_cfg.get("retry_base_delay", 2.0)

    prompt_template = _load_prompt_template()

    # Compute heuristic signals for all items
    items_with_signals: list[tuple[RawItem, FirsthandSignals]] = []
    for item in items:
        signals = compute_firsthand_signals(item.body)
        items_with_signals.append((item, signals))

    # Prioritize by heuristic score for cap enforcement
    score_order = {
        "strong_yes": 0, "weak_yes": 1, "neutral": 2,
        "weak_no": 3, "strong_no": 4,
    }
    items_with_signals.sort(
        key=lambda x: score_order.get(x[1].heuristic_firsthand_score, 5)
    )

    # Cap
    if len(items_with_signals) > max_calls:
        _log.warning(
            "Extraction candidates (%d) exceed cap (%d); truncating",
            len(items_with_signals), max_calls,
        )
        items_with_signals = items_with_signals[:max_calls]

    records: list[ExtractedRecord] = []
    successes = 0
    failures = 0

    for idx, (item, heuristic) in enumerate(items_with_signals, 1):
        prompt = prompt_template.format(
            source_type=item.item_type,
            drug_name=canonical_name,
            aliases=", ".join(aliases),
            text=item.body[:2000],
            has_first_person_pronoun=heuristic.has_first_person_pronoun,
            has_self_use_verb=heuristic.has_self_use_verb,
            has_secondhand_marker=heuristic.has_secondhand_marker,
            has_advice_only_pattern=heuristic.has_advice_only_pattern,
            heuristic_firsthand_score=heuristic.heuristic_firsthand_score,
            schema=_EXTRACTION_SCHEMA,
        )

        try:
            raw_response = call_llm(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=max_retries,
                retry_base_delay=retry_delay,
                response_format={"type": "json_object"},
            )
            record = _parse_llm_response(
                raw_response, item, heuristic, drug_query, canonical_name,
            )
            if record is not None:
                records.append(record)
                successes += 1
            else:
                failures += 1
        except LLMCallError as e:
            _log.error("Extraction failed for %s: %s", item.reddit_id, e)
            failures += 1

        if idx % 25 == 0 or idx == len(items_with_signals):
            _log.info(
                "Extraction progress: %d/%d (success=%d, fail=%d)",
                idx, len(items_with_signals), successes, failures,
            )

    return records, successes, failures
