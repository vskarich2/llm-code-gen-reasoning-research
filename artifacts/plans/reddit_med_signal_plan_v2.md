# Reddit Medication Side-Effect Signal Tool — Design Plan v2

**Date:** 2026-04-02
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Type:** Separate side project. Not part of the main benchmark/LEG/code-generation research.
**Target:** 1.5-2 day MVP build
**Supersedes:** reddit_med_signal_plan_v1.md

---

## 1. Executive Summary

A CLI tool that takes a medication name, retrieves relevant Reddit posts and their comment threads, extracts structured first-person experience reports grounded in source text, normalizes effect labels deterministically, aggregates them with nuanced contradiction handling, and produces a Markdown report with visible reliability metrics, principled example selection, and hardcoded disclaimers. The pipeline is:

**query → retrieval (posts + comments) → heuristic pre-filter → hybrid firsthand classification → LLM grounded extraction → deterministic normalization → deterministic aggregation → LLM report generation**

No databases, no vector stores, no web frameworks. CLI in, Markdown out, everything cached to JSONL on disk. Total cost per run: $0.05-0.20.

---

## 2. What Changes From V1

| V1 Flaw | What Was Wrong | V2 Fix |
|---------|---------------|--------|
| **Comments as afterthought** | V1 said "posts + top-level comments" but didn't justify it, didn't analyze tradeoffs, and treated comments as supplementary. In reality, comments often contain the richest anecdotal detail — direct experience corrections, dosage specifics, temporal context. | V2 defines an explicit retrieval policy (Section 4) with three tiers analyzed, selects posts + all top-level comments + high-signal second-level replies, and treats comments as first-class extraction targets. |
| **LLM normalization overtrust** | V1 asked the LLM to normalize effects during extraction ("nausea", "weight_gain") and grouped on those strings directly. LLMs are inconsistent: one call produces "weight_loss", another "lost_weight", another "dropped_weight". Aggregation on raw LLM labels fragments identical effects. | V2 adds a deterministic post-extraction normalization layer (Section 11): lowercase + punctuation strip + synonym map + YAML overrides. LLM labels are inputs, not final answers. |
| **Naive firsthand classification** | V1 delegated "is this firsthand?" entirely to the LLM. LLMs are unreliable classifiers for this: they over-include advice posts and miss ambiguous self-reference. | V2 adds hybrid classification (Section 9): heuristic regex signals + LLM judgment + a decision table for disagreements. Neither source is trusted alone. |
| **Ungrounded extraction** | V1 let the LLM freely state effects without requiring evidence from the source text. This enables hallucinated or inferred effects that the user never actually described. | V2 requires `effect_evidence_span` — the literal text substring (or tight paraphrase) that supports each extracted effect (Section 10). Extraction without evidence is discarded. |
| **Shallow contradiction detection** | V1 detected "positive vs. negative directionality on the same effect" and called it a contradiction. This mislabels temporal variation (nausea early → resolved later), dose-dependent differences, and expected population heterogeneity. | V2 adds a nuanced conflict taxonomy (Section 12): direct contradiction, temporal/stage variation, dose/context variation, and unresolved heterogeneity. |
| **Arbitrary example selection** | V1 said "up to 3 raw text excerpts" per theme with no selection policy. This produces garbage quotes — short, ambiguous, or secondhand snippets. | V2 defines a deterministic scoring function for excerpt ranking (Section 13) based on firsthand confidence, specificity, length, and clarity. |
| **Invisible failures** | V1 logged failures to stderr but the report itself didn't surface them. A report built on 40% extraction failures looked identical to one with 0% failures. | V2 adds a mandatory Reliability section to every report (Section 14) with retrieval counts, filter drop rates, extraction failures, confidence distribution, and sparse-data warnings. |
| **No hard caps** | V1 had configurable limits but no hard ceilings. A drug with 10,000 Reddit posts could produce an unbounded run. | V2 defines explicit hard caps at every stage (Section 15) with truncation/prioritization behavior when limits are hit. |

---

## 3. Scope and Non-Goals

### In scope (MVP)
- Single-drug query per run
- Reddit retrieval via PRAW (official API): posts + comments (see Section 4)
- Heuristic pre-filtering + hybrid firsthand classification
- LLM-powered grounded extraction with evidence spans
- Deterministic post-extraction normalization via synonym map
- Deterministic aggregation with nuanced contradiction taxonomy
- Principled example snippet selection
- Markdown report with hardcoded disclaimers, visible reliability metrics, raw examples
- Disk-cached raw retrieval and extracted records (JSONL)
- CLI interface with hard budget caps
- Brand/generic name expansion via curated YAML alias file

### Non-goals (unchanged from V1)
- Scientific validity, prevalence estimation, or pharmacovigilance claims
- Treatment recommendations or diagnostic output
- Real-time monitoring, web UI, or embedding-based search
- Integration with the main repo's research pipeline

---

## 4. Retrieval Policy (Posts + Comments)

### Why comments matter

On Reddit, posts about medications often take one of two forms:
1. **Question posts:** "Anyone else experience X on [drug]?" — the post itself has no anecdotal data. The value is entirely in the comments, where 5-30 people describe their experiences.
2. **Experience posts:** The OP describes their experience, and comments add corrections, variations, dosage context, and temporal detail ("same thing happened to me but it went away after 3 weeks").

In both cases, **comments contain the majority of first-person experience data.** A retrieval system that only captures posts discards the richest signal. This is not optional — it is the primary data source.

### Tradeoff analysis

| Strategy | Items per post | Signal quality | API cost | Noise |
|----------|---------------|----------------|----------|-------|
| **Posts only** | 1 | LOW — misses most firsthand reports | Lowest | Low |
| **Posts + top-level comments** | 1 + ~5-15 | GOOD — captures direct experience replies | Moderate | Moderate |
| **Posts + top-level + second-level replies** | 1 + ~15-40 | HIGH — captures "me too" confirmations and corrections | Higher | Higher |
| **Full comment trees** | 1 + ~50-200 | Diminishing — deep threads are tangential arguments | Very high | Very high |

### MVP policy: Posts + top-level comments + selected second-level replies

**Concrete rules:**

1. For each post returned by search, fetch the full comment forest via PRAW's `submission.comments`.
2. **Top-level comments:** Include ALL top-level comments (these are direct responses to the post and have the highest firsthand-experience density).
3. **Second-level replies:** Include a second-level reply IF it is a direct reply to a top-level comment AND has `score >= 3` (mild popularity filter) AND `len(body) >= 80` characters (filters out "same" and "lol" replies). This captures substantive "me too, but different" responses without diving into argument chains.
4. **Deeper replies (level 3+):** Excluded. These are almost always meta-discussion, arguments, or jokes.
5. **`MoreComments` expansion:** Do NOT call `replace_more()` for MVP. Top-level comments and visible second-level replies are sufficient. `replace_more()` is slow, rate-limit-heavy, and returns diminishing content.

**Why the score >= 3 filter on second-level replies is not a dumb popularity proxy:**

The score filter is applied ONLY to second-level replies, ONLY as a noise gate. It is never applied to posts or top-level comments. The threshold is deliberately low (3, not 50) — it exists to exclude zero-engagement one-word replies, not to select for popularity. Top-level comments (the primary comment data source) have no score filter.

**Retrieval data flow:**

```
For each subreddit in allowlist:
  For each alias in drug_aliases:
    search(alias, sort="relevance", time_filter=config, limit=per_sub_limit)
    For each post returned:
      → emit RawItem(type="post", ...)
      For each top-level comment:
        → emit RawItem(type="comment", depth=1, ...)
        For each second-level reply where score >= 3 and len >= 80:
          → emit RawItem(type="comment", depth=2, ...)
  Deduplicate by reddit_id
  Apply total_item_cap
```

**Expected yield:** For a moderately discussed drug, a search across 5 subreddits with limit=25 posts/subreddit yields ~100-125 posts and ~300-600 comments before deduplication and cap. After the hard cap of 500 items, ~60-70% will be comments.

---

## 5. User Workflow

```
$ cd side_projects/reddit_med_signal
$ python -m reddit_med_signal "metformin"

[1/6] Resolving drug aliases: metformin → metformin, glucophage, fortamet
[2/6] Retrieving Reddit posts + comments (hard cap: 500 items)...
      Searched 5 subreddits. Found 87 posts, 312 comments (399 items).
      Cached to data/raw/metformin_20260402_183012.jsonl
[3/6] Heuristic pre-filtering: 399 → 298 items (101 dropped)
[4/6] Hybrid firsthand classification + grounded extraction (298 LLM calls)...
      Progress: 298/298 [====================] 100%
      Firsthand (high confidence): 187
      Firsthand (medium confidence): 34
      Non-firsthand / excluded: 77
      Extraction failures: 3
      Cached to data/extracted/metformin_20260402_183012.jsonl
[5/6] Normalizing effect labels: 412 raw labels → 89 canonical buckets
[6/6] Aggregating and generating report...
      Report: reports/metformin_20260402_183012.md

Cost: ~$0.14 (298 extraction calls @ gpt-4.1-nano + 1 summary call @ gpt-4.1-mini)
Done.
```

---

## 6. Revised Data Flow

```
                         ┌──────────────┐
                         │ Drug aliases  │ (YAML, manually curated)
                         └──────┬───────┘
                                │
                   ┌────────────▼──────────────┐
 User input ──────▶  1. QUERY EXPANSION        │
 "metformin"       │  YAML lookup, no LLM      │
                   └────────────┬───────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  2. RETRIEVAL (PRAW)           │
                   │  Posts + top-level comments    │
                   │  + filtered second-level       │
                   │  Cache raw JSONL to disk       │
                   │  HARD CAP: 500 items           │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  3. HEURISTIC PRE-FILTER       │
                   │  Length, deleted, bots, URLs,   │
                   │  non-English                    │
                   │  HARD CAP: 400 after filter     │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  4. HYBRID FIRSTHAND           │
                   │     CLASSIFICATION             │
                   │  Heuristic regex signals        │
                   │  + LLM judgment (in extraction) │
                   │  + decision table               │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  5. GROUNDED LLM EXTRACTION    │
                   │  Per-item structured extract    │
                   │  Evidence spans required        │
                   │  HARD CAP: 350 LLM calls       │
                   │  Cache extracted JSONL          │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  6. DETERMINISTIC              │
                   │     NORMALIZATION              │
                   │  lowercase + strip + synonym   │
                   │  map + YAML overrides          │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  7. DETERMINISTIC              │
                   │     AGGREGATION                │
                   │  Group, count, detect conflicts │
                   │  Nuanced contradiction taxonomy │
                   │  Principled example selection   │
                   └────────────┬──────────────────┘
                                │
                   ┌────────────▼──────────────────┐
                   │  8. REPORT GENERATION          │
                   │  LLM summary from structured   │
                   │  data (NOT raw text)            │
                   │  + hardcoded disclaimers        │
                   │  + reliability section          │
                   └────────────┬──────────────────┘
                                │
                           report.md
```

---

## 7. Revised Module/Directory Plan

```
side_projects/
  reddit_med_signal/
    __main__.py              # CLI entry point
    cli.py                   # Click CLI with hard caps
    config.py                # Load YAML config
    retrieval.py             # PRAW: posts + comments per policy
    filtering.py             # Heuristic pre-filters
    firsthand.py             # Heuristic firsthand signals (regex-based)
    extraction.py            # Grounded LLM extraction with evidence spans
    normalization.py         # Deterministic effect label canonicalization  [NEW]
    aggregation.py           # Grouping + nuanced contradiction taxonomy
    example_selection.py     # Deterministic excerpt scoring + ranking      [NEW]
    report.py                # LLM summary + hardcoded disclaimers + reliability section
    schemas.py               # All Pydantic models
    drug_aliases.py          # Load + resolve brand/generic aliases
    llm_client.py            # Thin OpenAI wrapper with timeout + retry
    prompts/
      extraction.txt         # Grounded extraction prompt
      summarization.txt      # Report summarization prompt
    config/
      default.yaml           # Default config (subreddits, limits, model, caps)
      drug_aliases.yaml      # Brand/generic name mapping
      effect_synonyms.yaml   # Deterministic normalization map               [NEW]
    data/
      raw/                   # Cached raw Reddit payloads (JSONL)
      extracted/             # Cached extracted structured records (JSONL)
    reports/                 # Generated Markdown reports
    tests/
      __init__.py
      test_filtering.py
      test_firsthand.py      # Heuristic firsthand signal tests              [NEW]
      test_extraction.py
      test_normalization.py  # Canonicalization tests                        [NEW]
      test_aggregation.py
      test_example_selection.py  # Excerpt ranking tests                     [NEW]
      test_report.py
      test_schemas.py
      test_cli.py
      fixtures/
        raw_metformin_sample.jsonl
        extracted_metformin_sample.jsonl
        sparse_drug_sample.jsonl
        noisy_meme_sample.jsonl
        comment_heavy_thread.jsonl    # [NEW]
    README.md
    requirements.txt
```

Changes from V1: added `firsthand.py`, `normalization.py`, `example_selection.py`, `config/effect_synonyms.yaml`, and corresponding test files. No new dependencies.

---

## 8. Revised Schemas

### RawItem (retrieval output)

```python
class RawItem(BaseModel):
    item_type: Literal["post", "comment"]
    reddit_id: str
    subreddit: str
    url: str
    author: str | None
    created_utc: float
    score: int
    title: str | None              # posts only
    body: str
    parent_post_id: str | None     # comments only
    comment_depth: int             # 0 for posts, 1 for top-level, 2 for second-level  [NEW]
    parent_comment_id: str | None  # second-level comments only                         [NEW]
    retrieved_at: str
```

### FirsthandSignals (hybrid classification output)

```python
class FirsthandSignals(BaseModel):
    """Heuristic signals computed before LLM call."""
    has_first_person_pronoun: bool       # "I", "my", "me", "myself"
    has_self_use_verb: bool              # "I took", "I've been on", "started taking"
    has_secondhand_marker: bool          # "my friend", "my patient", "someone I know"
    has_advice_only_pattern: bool        # "you should try", "I'd recommend", no self-report
    has_speculation_marker: bool         # "I think it might", "probably causes"
    heuristic_firsthand_score: Literal["strong_yes", "weak_yes", "neutral", "weak_no", "strong_no"]
```

### ReportedEffect (revised for grounding)

```python
class ReportedEffect(BaseModel):
    effect_raw: str                      # LLM's label: "lost weight"
    effect_evidence_span: str            # literal text span: "I dropped about 15 pounds"  [NEW]
    effect_normalized: str               # post-normalization canonical: "weight_loss"      [MOVED to post-extraction]
    directionality: Literal["positive", "negative", "neutral", "ambiguous"]
    severity_hint: Literal["mild", "moderate", "severe", "unspecified"]
    is_secondorder: bool
    secondorder_chain: str | None
    temporal_context: str | None         # "after 2 weeks", "first month", "ongoing"       [RENAMED for clarity]
    extraction_confidence: Literal["high", "medium", "low"]  # LLM's own confidence        [NEW]
```

**Note on `effect_normalized`:** The LLM still produces `effect_raw`. The deterministic normalization layer (Section 11) computes `effect_normalized` AFTER extraction. During extraction, only `effect_raw` and `effect_evidence_span` are populated by the LLM. `effect_normalized` is added by `normalization.py`.

### ExtractedRecord (revised)

```python
class ExtractedRecord(BaseModel):
    drug_query: str
    canonical_drug_name: str
    source_type: Literal["post", "comment"]
    subreddit: str
    reddit_id: str
    url: str
    authored_timestamp: float
    text_excerpt: str                    # source text, truncated to 800 chars
    comment_depth: int                   # 0=post, 1=top-level, 2=second-level          [NEW]

    # Hybrid firsthand classification
    firsthand_heuristic: FirsthandSignals                                                [NEW]
    firsthand_llm: bool                  # LLM's judgment
    firsthand_llm_confidence: Literal["high", "medium", "low"]
    firsthand_final: bool                # resolved via decision table                   [NEW]
    firsthand_final_confidence: Literal["high", "medium", "low"]                         [NEW]

    mentions_personal_use: bool
    reported_effects: list[ReportedEffect]
    co_medications: list[str]
    temporal_info: str | None
    uncertainty_flags: list[str]
    extraction_notes: str | None
```

### Example Extracted Record (from a comment, not a post)

```json
{
  "drug_query": "sertraline",
  "canonical_drug_name": "sertraline",
  "source_type": "comment",
  "subreddit": "zoloft",
  "reddit_id": "t1_kx92fa1",
  "url": "https://reddit.com/r/zoloft/comments/abc123/slug/kx92fa1",
  "authored_timestamp": 1711929600.0,
  "text_excerpt": "I've been on 50mg Zoloft for about 6 weeks now. The first two weeks I had horrible nausea every morning, like I couldn't eat breakfast at all. That mostly went away by week 3. The biggest thing for me is the emotional blunting — I'm not anxious anymore but I also don't feel excited about anything. My wife noticed before I did. Also zero sex drive, which is rough.",
  "comment_depth": 1,
  "firsthand_heuristic": {
    "has_first_person_pronoun": true,
    "has_self_use_verb": true,
    "has_secondhand_marker": false,
    "has_advice_only_pattern": false,
    "has_speculation_marker": false,
    "heuristic_firsthand_score": "strong_yes"
  },
  "firsthand_llm": true,
  "firsthand_llm_confidence": "high",
  "firsthand_final": true,
  "firsthand_final_confidence": "high",
  "mentions_personal_use": true,
  "reported_effects": [
    {
      "effect_raw": "horrible nausea every morning",
      "effect_evidence_span": "The first two weeks I had horrible nausea every morning, like I couldn't eat breakfast at all",
      "effect_normalized": "nausea",
      "directionality": "negative",
      "severity_hint": "moderate",
      "is_secondorder": false,
      "secondorder_chain": null,
      "temporal_context": "first 2 weeks, resolved by week 3",
      "extraction_confidence": "high"
    },
    {
      "effect_raw": "emotional blunting",
      "effect_evidence_span": "The biggest thing for me is the emotional blunting — I'm not anxious anymore but I also don't feel excited about anything",
      "effect_normalized": "emotional_blunting",
      "directionality": "negative",
      "severity_hint": "moderate",
      "is_secondorder": false,
      "secondorder_chain": null,
      "temporal_context": "ongoing at 6 weeks",
      "extraction_confidence": "high"
    },
    {
      "effect_raw": "zero sex drive",
      "effect_evidence_span": "Also zero sex drive, which is rough",
      "effect_normalized": "libido_decrease",
      "directionality": "negative",
      "severity_hint": "severe",
      "is_secondorder": false,
      "secondorder_chain": null,
      "temporal_context": "ongoing at 6 weeks",
      "extraction_confidence": "high"
    }
  ],
  "co_medications": [],
  "temporal_info": "6 weeks on 50mg; nausea resolved by week 3; blunting and libido ongoing",
  "uncertainty_flags": [],
  "extraction_notes": "Wife noticed emotional blunting — external corroboration of self-report."
}
```

---

## 9. Hybrid Filtering and Firsthand Classification Design

### Stage 1: Heuristic Pre-Filter (deterministic, no LLM)

Same as V1. Removes junk before any LLM call:
- `len(body) < 30` → drop
- `[deleted]` / `[removed]` → drop
- Bot authors (AutoModerator, `*Bot` pattern, small blocklist) → drop
- Body >80% URLs → drop
- Non-English heuristic (>50% non-common-English words) → drop

### Stage 2: Heuristic Firsthand Signals (`firsthand.py`)

Computed BEFORE the LLM call. Pure regex, no LLM cost.

```python
import re

# Patterns
FIRST_PERSON = re.compile(r'\b(I|my|me|myself|I\'m|I\'ve|I\'d)\b', re.IGNORECASE)
SELF_USE_VERBS = re.compile(
    r'\b(I\s+(?:took|take|started|stopped|switched|been on|was on|am on|tried|use|using))\b',
    re.IGNORECASE
)
SECONDHAND = re.compile(
    r'\b(my (?:friend|mom|dad|sister|brother|wife|husband|partner|patient|client|kid|son|daughter)|'
    r'someone I know|a person I|they (?:took|started|tried))\b',
    re.IGNORECASE
)
ADVICE_ONLY = re.compile(
    r'\b(you should|I\'d recommend|I would suggest|have you tried|try taking|consider asking)\b',
    re.IGNORECASE
)
SPECULATION = re.compile(
    r'\b(I think it (?:might|could|may)|probably causes|supposedly|I heard that|I read that)\b',
    re.IGNORECASE
)

def compute_firsthand_signals(text: str) -> FirsthandSignals:
    fp = bool(FIRST_PERSON.search(text))
    sv = bool(SELF_USE_VERBS.search(text))
    sh = bool(SECONDHAND.search(text))
    ao = bool(ADVICE_ONLY.search(text)) and not sv  # advice without self-use
    sp = bool(SPECULATION.search(text)) and not sv   # speculation without self-use

    # Scoring
    if sv and not sh:
        score = "strong_yes"
    elif fp and not sh and not ao:
        score = "weak_yes"
    elif sh and not sv:
        score = "weak_no"
    elif ao and not fp:
        score = "strong_no"
    elif sp and not sv:
        score = "weak_no"
    else:
        score = "neutral"

    return FirsthandSignals(
        has_first_person_pronoun=fp,
        has_self_use_verb=sv,
        has_secondhand_marker=sh,
        has_advice_only_pattern=ao,
        has_speculation_marker=sp,
        heuristic_firsthand_score=score,
    )
```

### Stage 3: LLM Firsthand Judgment (inside extraction call)

The extraction prompt asks the LLM to output `firsthand_llm: true/false` and `firsthand_llm_confidence: high/medium/low`. This is part of the extraction call, not a separate call — no additional cost.

### Stage 4: Decision Table (deterministic resolution)

The heuristic score and LLM judgment are combined via a fixed decision table:

| Heuristic Score | LLM Firsthand | LLM Confidence | → Final Decision | → Final Confidence |
|-----------------|---------------|----------------|-------------------|--------------------|
| strong_yes | true | high | **INCLUDE** | high |
| strong_yes | true | medium | **INCLUDE** | high |
| strong_yes | true | low | **INCLUDE** | medium |
| strong_yes | false | any | **INCLUDE** | medium *(heuristic overrides — likely LLM missed self-use verbs)* |
| weak_yes | true | high | **INCLUDE** | high |
| weak_yes | true | medium/low | **INCLUDE** | medium |
| weak_yes | false | any | **FLAG** | low *(borderline — included in report with low-confidence marker)* |
| neutral | true | high | **INCLUDE** | medium |
| neutral | true | medium/low | **FLAG** | low |
| neutral | false | any | **EXCLUDE** | — |
| weak_no | true | high | **FLAG** | low *(LLM disagrees with heuristic — keep but flag)* |
| weak_no | true | medium/low | **EXCLUDE** | — |
| weak_no | false | any | **EXCLUDE** | — |
| strong_no | true | any | **EXCLUDE** | — *(heuristic is confident this is secondhand/advice; LLM is wrong)* |
| strong_no | false | any | **EXCLUDE** | — |

**Key principle:** When heuristic says "strong_yes" but LLM says "no," trust the heuristic — self-use verbs like "I've been on metformin for 3 months" are reliable positive signals that LLMs sometimes miss. When heuristic says "strong_no" (secondhand markers, advice-only), override the LLM even if it says "yes" — phrases like "my patient takes" are definitive secondhand markers.

**FLAGged items** are included in aggregation but tagged with `firsthand_final_confidence: "low"`. The report's reliability section counts them. The aggregation step treats them as normal records but the example selection policy (Section 13) penalizes them.

---

## 10. Grounded Extraction Design

### The problem with V1

V1 allowed the LLM to freely state effects. If the source text says "I felt weird," V1's LLM might extract `effect_raw: "cognitive_impairment"` — an inference, not an extraction. The user never said "cognitive impairment." This is over-inference and it is not acceptable.

### V2 grounding contract

The extraction prompt (Section 16) requires the LLM to output:
- `effect_raw`: the LLM's short label for the effect (e.g., "nausea")
- `effect_evidence_span`: a **literal substring** from the source text that supports this effect (e.g., "I had horrible nausea every morning")

**Validation rule (enforced in `extraction.py`):**

```python
def validate_grounding(effect: ReportedEffect, source_text: str) -> bool:
    """Check that evidence span appears in (or is a close substring of) source text."""
    span = effect.effect_evidence_span.lower().strip()
    text = source_text.lower()
    # Exact substring match
    if span in text:
        return True
    # Fuzzy: at least 80% of span words appear in text (handles minor LLM paraphrasing)
    span_words = set(span.split())
    text_words = set(text.split())
    overlap = len(span_words & text_words) / max(len(span_words), 1)
    return overlap >= 0.8
```

**If an effect fails grounding validation:** the effect is dropped from that record and an `uncertainty_flag: "ungrounded_effect_dropped"` is added. The record itself is not dropped — other grounded effects in the same record are preserved.

**What counts as grounded:**
- Direct quote: `"I had terrible nausea"` → evidence span: `"I had terrible nausea"` ✓
- Tight paraphrase: User wrote `"couldn't sleep at all"` → evidence span: `"couldn't sleep at all"` ✓
- Loose inference: User wrote `"felt weird"` → evidence span: `"felt weird"` with effect_raw: `"malaise"` ✓ (the span is real; the label is the LLM's interpretation, which is fine)
- Hallucination: User wrote nothing about sleep → evidence span: `"had trouble sleeping"` ✗ (span not in text, dropped)

### Extraction confidence

The LLM also outputs `extraction_confidence: high/medium/low` per effect. This is used by the example selection policy, not for filtering. Even "low" confidence effects are kept if they pass grounding validation — the evidence span is the real quality gate.

---

## 11. Deterministic Normalization and Canonicalization Design

### The problem with V1

V1 relied on the LLM to produce consistent canonical labels. In practice:
- Call 1 produces `"weight_loss"` for "I dropped 15 pounds"
- Call 2 produces `"lost_weight"` for "lost a bunch of weight"  
- Call 3 produces `"dropped_weight"` for "the weight just came off"
- Call 4 produces `"weight_decrease"` for "I weigh less now"

These are all the same effect. V1's aggregation would count them as 4 separate effects with 1 mention each. That's useless.

### V2 normalization pipeline

```
LLM extraction → effect_raw (inconsistent) → normalization.py → effect_normalized (canonical)
```

**Step 1: Text cleanup**
```python
def clean_label(raw: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace."""
    label = raw.lower().strip()
    label = re.sub(r'[^a-z0-9_\s]', '', label)
    label = re.sub(r'\s+', '_', label)
    return label
```

**Step 2: Synonym map lookup**

The synonym map is a YAML file that maps variant labels to canonical labels:

```yaml
# config/effect_synonyms.yaml

# Weight
weight_loss:
  - lost_weight
  - losing_weight
  - dropped_weight
  - weight_decrease
  - dropped_pounds
  - weight_came_off
  - shedding_weight
  - slimmed_down
weight_gain:
  - gained_weight
  - gaining_weight
  - put_on_weight
  - weight_increase
  - weight_went_up
  - packed_on_pounds

# GI
nausea:
  - nauseous
  - felt_nauseous
  - feeling_sick
  - queasy
  - sick_to_stomach
  - upset_stomach_nausea
diarrhea:
  - loose_stools
  - runny_stomach
  - gi_issues_diarrhea
stomach_pain:
  - stomach_cramps
  - stomach_ache
  - abdominal_pain
  - gut_pain
  - belly_pain
appetite_decrease:
  - lost_appetite
  - no_appetite
  - appetite_loss
  - reduced_appetite
  - killed_appetite
  - couldnt_eat
appetite_increase:
  - increased_appetite
  - hungry_all_the_time
  - appetite_went_up
  - constant_hunger

# Sleep
insomnia:
  - couldnt_sleep
  - cant_sleep
  - trouble_sleeping
  - sleep_problems
  - wide_awake
  - sleeplessness
drowsiness:
  - sleepy
  - sleepiness
  - tired_all_the_time
  - excessive_sleep
  - oversleeping
  - knocked_out

# Mood
mood_improvement:
  - felt_better
  - mood_better
  - improved_mood
  - feeling_good
  - less_depressed
mood_worsening:
  - mood_worse
  - felt_worse
  - more_depressed
  - depression_worsened
emotional_blunting:
  - flat_affect
  - feeling_nothing
  - numb
  - emotional_numbness
  - zombified
  - zombie_feeling

# Sexual
libido_decrease:
  - low_libido
  - no_sex_drive
  - lost_sex_drive
  - zero_libido
  - sexual_dysfunction
  - no_interest_in_sex
libido_increase:
  - higher_libido
  - increased_sex_drive

# Cognitive
brain_fog:
  - foggy
  - mental_fog
  - cloudy_thinking
  - cognitive_issues
  - cant_think_clearly
improved_focus:
  - better_focus
  - clearer_thinking
  - sharper
  - more_focused

# Other common
headache:
  - headaches
  - head_pain
dry_mouth:
  - cotton_mouth
  - mouth_dry
sweating:
  - excessive_sweating
  - night_sweats
  - sweaty
dizziness:
  - dizzy
  - lightheaded
  - vertigo
fatigue:
  - exhaustion
  - exhausted
  - no_energy
  - tired
  - wiped_out
anxiety_decrease:
  - less_anxious
  - anxiety_better
  - reduced_anxiety
  - anxiety_gone
anxiety_increase:
  - more_anxious
  - anxiety_worse
  - increased_anxiety
  - anxiety_worsened
```

**Step 3: Canonicalize**

```python
def canonicalize_effect(raw_label: str, synonym_map: dict[str, list[str]]) -> str:
    """Map a raw LLM label to its canonical form. Falls through to cleaned raw if no match."""
    cleaned = clean_label(raw_label)

    # Direct match to a canonical key
    if cleaned in synonym_map:
        return cleaned

    # Match to a synonym
    for canonical, synonyms in synonym_map.items():
        if cleaned in synonyms:
            return canonical

    # No match — return the cleaned raw label as-is
    # These become candidates for adding to the synonym map later
    return cleaned
```

**Step 4: Apply to all extracted records**

```python
def normalize_records(records: list[ExtractedRecord], synonym_map: dict) -> list[ExtractedRecord]:
    for record in records:
        for effect in record.reported_effects:
            effect.effect_normalized = canonicalize_effect(effect.effect_raw, synonym_map)
    return records
```

**Unmapped labels:** If `canonicalize_effect` returns the cleaned raw label (no synonym match), the label is used as-is in aggregation. The report's reliability section lists all unmapped labels so the user can add them to the synonym map for future runs.

**Why not use the LLM for normalization?** Because the point of normalization is CONSISTENCY, and LLMs are not consistent across calls. A deterministic map guarantees that "lost_weight" and "dropped_pounds" always map to "weight_loss" — every time, on every run, with zero cost and zero variance. The synonym map starts at ~100 entries and grows as the user adds unmapped labels. This is the right tool for the job.

---

## 12. Aggregation and Contradiction Handling

### Basic aggregation (unchanged from V1)

1. Drop records where `firsthand_final == False`
2. Group by `effect_normalized`
3. Count mentions per canonical effect
4. Compute directionality breakdown per effect
5. Compute severity breakdown per effect
6. Detect co-medications
7. Flag sparse data if total firsthand records < 10

### Revised contradiction/conflict taxonomy

V1 treated all opposing signals as "contradictions." This is wrong. If 20 people report insomnia in the first week and 15 report drowsiness after month 2, that is not a contradiction — it is a well-known temporal pattern. Calling it a "contradiction" misleads the reader.

**V2 conflict taxonomy:**

```python
class ConflictType(str, Enum):
    DIRECT_CONTRADICTION = "direct_contradiction"
    TEMPORAL_VARIATION = "temporal_variation"
    DOSE_CONTEXT_VARIATION = "dose_context_variation"
    UNRESOLVED_HETEROGENEITY = "unresolved_heterogeneity"

class ConflictRecord(BaseModel):
    effect_a: str                   # canonical effect name
    effect_b: str                   # canonical effect name (if cross-effect)
    conflict_type: ConflictType
    evidence_summary: str           # brief explanation
    count_a: int
    count_b: int
    example_a: str                  # excerpt from an effect_a record
    example_b: str                  # excerpt from an effect_b record
```

**Detection rules (deterministic):**

**Rule 1 — Temporal variation detection:**

If an effect pair (e.g., insomnia vs. drowsiness) has records where the `temporal_context` fields cluster differently:
- Effect A records mostly mention early timeframes ("first week", "initially", "starting out")
- Effect B records mostly mention later timeframes ("after a month", "eventually", "long-term")
→ Classify as `TEMPORAL_VARIATION`.

Implementation: simple keyword matching on `temporal_context`:
```python
EARLY_MARKERS = {"first week", "first month", "initially", "starting", "early", "beginning", "day 1", "week 1", "week 2"}
LATE_MARKERS = {"eventually", "after a month", "months later", "long-term", "over time", "settled", "wore off"}

def classify_temporal_pattern(records_a, records_b) -> ConflictType | None:
    a_temporal = [r.temporal_context or "" for r in records_a]
    b_temporal = [r.temporal_context or "" for r in records_b]
    a_early = sum(1 for t in a_temporal if any(m in t.lower() for m in EARLY_MARKERS))
    b_late = sum(1 for t in b_temporal if any(m in t.lower() for m in LATE_MARKERS))
    if a_early > len(records_a) * 0.4 and b_late > len(records_b) * 0.4:
        return ConflictType.TEMPORAL_VARIATION
    return None
```

**Rule 2 — Dose/context variation detection:**

If records for opposing effects mention different dosages or contexts (e.g., "25mg" vs. "200mg", "with food" vs. "on empty stomach"), classify as `DOSE_CONTEXT_VARIATION`. Detection: regex for dosage patterns in `text_excerpt`.

**Rule 3 — Direct contradiction:**

If two opposing-directionality effects on the same dimension (e.g., weight_gain vs. weight_loss) exist with NO temporal or dose pattern detected, classify as `DIRECT_CONTRADICTION`.

**Rule 4 — Unresolved heterogeneity (default):**

If the conflict does not match Rules 1-3, classify as `UNRESOLVED_HETEROGENEITY` — "different people report different things, and we cannot explain why from the data."

**Conflict pairs to check:**

The aggregation step checks for opposing directionalities within semantic pairs. Pairs are defined in config:

```yaml
# Opposing effect pairs for contradiction detection
conflict_pairs:
  - [weight_gain, weight_loss]
  - [insomnia, drowsiness]
  - [appetite_increase, appetite_decrease]
  - [anxiety_increase, anxiety_decrease]
  - [mood_improvement, mood_worsening]
  - [libido_increase, libido_decrease]
  - [improved_focus, brain_fog]
```

### Revised AggregationResult

```python
class AggregationResult(BaseModel):
    drug_query: str
    canonical_drug_name: str
    total_raw_items: int
    total_after_heuristic_filter: int
    total_extraction_attempted: int
    total_extraction_succeeded: int
    total_extraction_failed: int
    total_firsthand_high: int
    total_firsthand_medium: int
    total_firsthand_low: int
    total_excluded: int
    is_sparse: bool
    themes: list[EffectTheme]
    conflicts: list[ConflictRecord]       # replaces V1 "contradictions"
    co_medication_counts: dict[str, int]
    uncertainty_summary: dict[str, int]
    unmapped_labels: list[str]            # raw labels not in synonym map  [NEW]
    run_timestamp: str
    config_snapshot: dict
```

---

## 13. Example Snippet Selection Policy

### The problem

Not all extracted text excerpts are equally useful. A report that quotes "same" or "yeah me too lol" or a 2000-word rambling post is useless. We need to select the best 2-3 examples per theme.

### Deterministic scoring function

Each candidate excerpt for a theme is scored on 5 dimensions:

```python
def score_excerpt(record: ExtractedRecord, effect: ReportedEffect) -> float:
    score = 0.0

    # 1. Firsthand confidence (0-3 points)
    confidence_scores = {"high": 3.0, "medium": 1.5, "low": 0.5}
    score += confidence_scores[record.firsthand_final_confidence]

    # 2. Evidence span specificity (0-2 points)
    span_len = len(effect.effect_evidence_span)
    if 40 <= span_len <= 300:
        score += 2.0   # good length — specific but not rambling
    elif 20 <= span_len < 40:
        score += 1.0   # short but present
    elif span_len > 300:
        score += 0.5   # too long, probably not a clean quote

    # 3. Temporal context present (0-1 point)
    if effect.temporal_context:
        score += 1.0

    # 4. Extraction confidence (0-1 point)
    if effect.extraction_confidence == "high":
        score += 1.0
    elif effect.extraction_confidence == "medium":
        score += 0.5

    # 5. Low uncertainty (0-1 point)
    if not record.uncertainty_flags:
        score += 1.0
    elif len(record.uncertainty_flags) == 1:
        score += 0.5

    return score
```

**Max score: 8.0.** For each theme, rank all candidate excerpts by score descending, select top 3. Ties broken by `authored_timestamp` descending (prefer more recent).

**The excerpt displayed in the report is `effect_evidence_span`, not the full `text_excerpt`.** This ensures the quote is relevant to the specific effect, not a random slice of a long post.

---

## 14. Logging, Reliability Reporting, and Caching

### Logging (same as V1)

Python `logging` to stderr. INFO for progress, WARNING for skipped items / sparse data, ERROR for failures. Every LLM call logs model, token count, latency, estimated cost.

### Mandatory Reliability Section in Report [NEW]

Every report includes a `## Data Reliability` section (generated deterministically, NOT by the LLM). This section is assembled by `report.py` from `AggregationResult` fields:

```markdown
## Data Reliability

| Metric | Value |
|--------|-------|
| Items retrieved (posts + comments) | 399 |
| Items dropped by heuristic filter | 101 (25%) |
| Items sent to extraction | 298 |
| Extraction successes | 295 |
| Extraction failures | 3 (1%) |
| Classified firsthand (high confidence) | 187 |
| Classified firsthand (medium confidence) | 34 |
| Classified firsthand (low confidence) | 12 |
| Excluded (non-firsthand / failed) | 62 |
| Ungrounded effects dropped | 7 |
| Unmapped effect labels | 4 (see below) |
| **Records used in aggregation** | **233** |

**Sparse data warning:** No — 233 firsthand records is adequate.

**Unmapped effect labels** (not in synonym map, used as-is):
- `jaw_clenching` (3 mentions)
- `vivid_dreams` (5 mentions)
- `taste_changes` (2 mentions)
- `muscle_twitches` (1 mention)

*Consider adding these to `config/effect_synonyms.yaml` for better aggregation in future runs.*
```

**This section cannot be suppressed.** It is hardcoded into the report template, not generated by the LLM.

### Caching (same as V1, with additions)

- **Raw retrieval:** `data/raw/{drug}_{timestamp}.jsonl`
- **Extracted records:** `data/extracted/{drug}_{timestamp}.jsonl`
- **Cache reuse:** `--from-cache {timestamp}` re-runs normalization + aggregation + report from cached extracted records
- **New: `--from-raw-cache {timestamp}`** re-runs extraction + normalization + aggregation + report from cached raw items (useful if you change the extraction prompt or synonym map)

---

## 15. Cost Controls and Hard Limits

### Hard caps (MVP defaults in `default.yaml`)

```yaml
limits:
  # Retrieval
  max_posts_per_subreddit: 25
  max_comments_per_post: 10          # top-level only; second-level filtered separately
  max_second_level_per_comment: 3    # per top-level comment
  total_raw_item_cap: 500            # absolute ceiling on retrieved items

  # Filtering
  max_items_after_heuristic: 400     # if more survive filtering, prioritize by score desc

  # Extraction
  max_extraction_calls: 350          # absolute ceiling on LLM calls per run
  extraction_timeout_seconds: 30     # per call
  extraction_model: "gpt-4.1-nano"

  # Report
  max_summary_input_tokens: 8000     # truncate aggregation JSON if needed
  summary_model: "gpt-4.1-mini"
  summary_timeout_seconds: 60

  # Budget
  max_cost_estimate_usd: 0.50       # abort if estimated cost exceeds this
```

### Truncation / prioritization behavior when caps are hit

**Retrieval cap (500 items):** When the total across all subreddits exceeds 500, prioritize by:
1. Posts before comments (posts establish context)
2. Top-level comments before second-level (higher signal density)
3. Within each tier, sort by `created_utc` descending (prefer recent)
4. Truncate at 500

**Heuristic filter cap (400 items):** If >400 items survive heuristic filtering, sort survivors by `len(body)` descending (longer items have more extractable content) and truncate at 400.

**Extraction cap (350 calls):** If >350 items need extraction, prioritize by firsthand heuristic score:
1. `strong_yes` items first
2. Then `weak_yes`
3. Then `neutral`
4. Truncate at 350 — `weak_no` and `strong_no` items are never sent to extraction anyway

**Summary input cap (8000 tokens):** If the serialized `AggregationResult` exceeds 8000 tokens, truncate themes to top 20 by mention count, truncate example excerpts to 2 per theme, and drop co-medication detail.

**Cost estimate check:** Before starting extraction, compute:
```
estimated_cost = num_extraction_calls * avg_extraction_cost + summary_cost
```
If `estimated_cost > max_cost_estimate_usd`, print warning and prompt user to confirm or abort. (CLI flag `--force` bypasses the check.)

---

## 16. Prompt Revisions

### Revised Extraction Prompt (`prompts/extraction.txt`)

```
You are extracting structured information from a Reddit {source_type} about a medication.

DRUG BEING QUERIED: {drug_name}
ALIASES: {aliases}

SOURCE TEXT:
---
{text}
---

HEURISTIC FIRSTHAND SIGNALS (pre-computed):
- First-person pronouns detected: {has_first_person_pronoun}
- Self-use verbs detected: {has_self_use_verb}
- Secondhand markers detected: {has_secondhand_marker}
- Advice-only pattern: {has_advice_only_pattern}
- Heuristic score: {heuristic_firsthand_score}

YOUR TASKS:

1. FIRSTHAND JUDGMENT: Is the author describing their OWN experience taking this medication?
   - "I've been on metformin for 3 months" → yes
   - "My friend tried Zoloft" → no (secondhand)
   - "You should try taking it with food" → no (advice, not experience)
   - "I heard it causes weight gain" → no (hearsay)
   Output: firsthand_llm (true/false) and firsthand_llm_confidence (high/medium/low)

2. EFFECT EXTRACTION: For each effect the author reports from THEIR OWN experience:
   a. effect_raw: your short label (e.g., "nausea", "lost weight")
   b. effect_evidence_span: the EXACT substring from the source text that describes this effect.
      CRITICAL: This must be a LITERAL QUOTE from the source text above. Copy it exactly.
      If you cannot point to a specific text span, DO NOT extract the effect.
   c. directionality: positive (helpful), negative (harmful), neutral, or ambiguous
   d. severity_hint: mild, moderate, severe, or unspecified
   e. is_secondorder: true if the effect is caused by another effect (e.g., appetite loss → weight loss)
   f. secondorder_chain: if is_secondorder, the chain (e.g., "appetite_decrease → weight_loss")
   g. temporal_context: when the effect appeared relative to starting the drug, if stated
   h. extraction_confidence: your confidence that this effect is real and correctly extracted

3. CO-MEDICATIONS: List any other drugs the author mentions taking concurrently.

4. TEMPORAL INFO: Summarize any timeline information (how long on drug, when effects appeared/resolved).

5. UNCERTAINTY FLAGS: Flag any of these that apply:
   - "speculative" — author is guessing, not reporting
   - "secondhand" — reporting someone else's experience
   - "unclear_causation" — author isn't sure the drug caused the effect
   - "multiple_drugs" — author is on several drugs, attribution unclear
   - "unclear_drug_reference" — post may not be about the queried drug

RULES:
- Extract ONLY effects explicitly described in the text. Do NOT infer effects.
- Every effect MUST have an evidence_span that is a literal substring of the source text.
- If the text is ambiguous, set extraction_confidence to "low" rather than guessing.
- If this is a comment, it may be responding to a post about the drug. The comment author's experience is what matters, not the post author's.
- Do NOT extract effects mentioned by someone else in the comment thread. Only the author of THIS text.

Respond with a JSON object matching this schema:
{schema}
```

### Revised Summarization Prompt (`prompts/summarization.txt`)

```
You are generating a structured Markdown report summarizing anecdotal Reddit reports about a medication.

STRICT RULES — VIOLATIONS ARE UNACCEPTABLE:
- Every claim must be labeled as anecdotal. Use "users reported", "commenters described", "anecdotal mentions".
- NEVER use "causes", "prevents", "treats", "common", "rare", "frequent", "prevalence".
- Say "N Reddit posts/comments mentioned X" — never "X occurs in N% of users".
- Contradictory effects: present BOTH sides. Do NOT resolve contradictions.
- Conflict types: use the conflict_type labels (temporal_variation, direct_contradiction, etc.) — do not flatten everything to "contradiction".
- If data is sparse, reduce confidence language.
- Include 2-3 raw example quotes per theme (from example_excerpts in the data).
- Do NOT add information not in the data below.
- Do NOT make treatment recommendations.
- Do NOT speculate about mechanisms.

AGGREGATED DATA:
{aggregation_json}

Generate Markdown with these sections:
1. ## Summary — 2-3 sentence overview
2. ## Most Frequently Mentioned Effects — table: effect | anecdotal mentions | direction | severity | example quote
3. ## Conflicting Reports — organized by conflict_type, not lumped together
4. ## Second-Order Effect Chains — if any
5. ## Co-Medications Frequently Mentioned — list with counts
6. ## Notes — uncertainty flags, data quality, anything else notable

Do NOT include a disclaimer or reliability section — those are added separately.
```

---

## 17. Test Plan Revisions

### New tests (additions to V1 test plan)

**`test_firsthand.py` [NEW]:**
- `test_strong_yes_self_use_verb`: "I've been taking metformin for 3 months" → strong_yes
- `test_strong_no_secondhand`: "My friend tried Zoloft and hated it" → strong_no with has_secondhand_marker=True
- `test_weak_yes_first_person_no_verb`: "My experience with Lexapro has been ok" → weak_yes
- `test_advice_only`: "You should definitely try taking it with food" → strong_no
- `test_speculation`: "I think it might cause weight gain" → weak_no
- `test_mixed_signals`: "I took it and my friend did too" → has both self_use_verb and secondhand_marker → neutral
- `test_decision_table_strong_yes_llm_no`: heuristic=strong_yes + LLM=false → INCLUDE at medium confidence
- `test_decision_table_strong_no_llm_yes`: heuristic=strong_no + LLM=true → EXCLUDE
- `test_decision_table_neutral_llm_yes_high`: heuristic=neutral + LLM=true+high → INCLUDE at medium

**`test_normalization.py` [NEW]:**
- `test_weight_loss_variants`: "lost_weight", "losing_weight", "dropped_pounds", "weight_came_off" all → "weight_loss"
- `test_nausea_variants`: "nauseous", "felt_nauseous", "sick_to_stomach", "queasy" all → "nausea"
- `test_case_insensitive`: "WEIGHT_LOSS", "Weight_Loss" → "weight_loss"
- `test_punctuation_stripped`: "weight-loss!", "weight.loss" → "weight_loss"
- `test_unmapped_passthrough`: "jaw_clenching" (not in map) → "jaw_clenching" (cleaned, returned as-is)
- `test_canonical_key_match`: "weight_loss" → "weight_loss" (already canonical)
- `test_whitespace_normalized`: "lost  weight" → "lost_weight" → "weight_loss"

**`test_extraction.py` (revised):**
- `test_grounding_valid`: Evidence span is literal substring of source → passes validation
- `test_grounding_fuzzy_valid`: Evidence span has 85% word overlap with source → passes
- `test_grounding_invalid`: Evidence span not in source text → effect dropped, uncertainty flag added
- `test_comment_extraction`: Extract from a comment (not post) — comment_depth=1, evidence grounded in comment body
- `test_multiple_effects_grounded`: Post with 3 effects, each with valid evidence span

**`test_aggregation.py` (revised):**
- `test_temporal_variation_not_contradiction`: insomnia records with "first week" temporal context + drowsiness records with "after a month" → classified as TEMPORAL_VARIATION, not DIRECT_CONTRADICTION
- `test_direct_contradiction`: weight_gain and weight_loss both present with no temporal/dose pattern → DIRECT_CONTRADICTION
- `test_dose_context_variation`: anxiety_decrease at "25mg" + anxiety_increase at "200mg" → DOSE_CONTEXT_VARIATION
- `test_unresolved_heterogeneity`: opposing effects with no detectable pattern → UNRESOLVED_HETEROGENEITY
- `test_low_confidence_records_included`: FLAGged records (low confidence) are included in aggregation count
- `test_unmapped_labels_listed`: Effects with no synonym match appear in `unmapped_labels`

**`test_example_selection.py` [NEW]:**
- `test_high_confidence_preferred`: High-confidence excerpt scores higher than low-confidence
- `test_good_length_preferred`: 100-char span scores higher than 15-char span
- `test_temporal_context_bonus`: Excerpt with temporal info scores higher than without
- `test_low_uncertainty_preferred`: Excerpt with no uncertainty flags scores higher
- `test_top_3_selected`: Given 10 candidates, exactly 3 with highest scores are selected
- `test_tie_broken_by_recency`: Equal-score excerpts sorted by timestamp descending

**`test_report.py` (revised):**
- `test_disclaimer_header_present`: Hardcoded disclaimer header appears verbatim
- `test_disclaimer_footer_present`: Hardcoded disclaimer footer appears verbatim
- `test_reliability_section_present`: "Data Reliability" section with table appears
- `test_reliability_shows_extraction_failures`: If 5 extractions failed, the reliability table says "5"
- `test_reliability_shows_unmapped_labels`: Unmapped labels listed in reliability section
- `test_no_prevalence_language`: Report does not contain "common", "frequent", "% of users", "prevalence", "rare"
- `test_no_treatment_language`: Report does not contain "recommend", "should take", "prescribe", "advise"
- `test_conflict_type_labels`: Conflicts in report use taxonomy labels (temporal_variation, etc.), not generic "contradiction"
- `test_sparse_warning_present`: Report with <10 firsthand records shows sparse-data warning

**`test_cli.py` (addition):**
- `test_from_raw_cache_flag`: `--from-raw-cache` skips retrieval but re-runs extraction
- `test_cost_cap_abort`: Estimated cost > max_cost_estimate_usd → aborts with message

**Test fixtures (additions):**
- `fixtures/comment_heavy_thread.jsonl`: 3 posts with 50+ comments — verifies comment extraction pipeline
- `fixtures/temporal_variation_sample.jsonl`: Records with clear early/late temporal patterns — verifies non-contradiction classification

---

## 18. Harsh Review of Still-Bad Alternatives

### Bad Idea 1: "Use the LLM for normalization instead of a synonym map"

**Why it's tempting:** Seems more flexible, handles novel labels automatically.

**Why it's bad:** The entire point of normalization is CONSISTENCY. An LLM that normalizes "lost weight" to "weight_loss" on call 1 and "weight_decrease" on call 2 defeats the purpose. You'd need a second normalization pass to fix the first — turtles all the way down. A 150-line YAML file solves the problem permanently, deterministically, at zero cost.

**Better alternative:** The synonym map in this plan. Grows over time as unmapped labels are identified. Takes 10 seconds to add an entry.

### Bad Idea 2: "Skip heuristic firsthand signals, just let the LLM classify"

**Why it's tempting:** The LLM is "smart enough," right?

**Why it's bad:** LLMs are unreliable binary classifiers on subtle distinctions like "is this firsthand?" They over-include advice posts ("you should try it with food" — is the advisor speaking from experience?). They miss ambiguous self-reference ("this drug is amazing" — firsthand or cheerleading?). The heuristic catches definitive signals (self-use verbs, secondhand markers) that the LLM sometimes misses. The hybrid approach uses both, trusts neither alone, and has an explicit resolution policy when they disagree.

**Better alternative:** The hybrid decision table in this plan.

### Bad Idea 3: "Use embeddings for effect clustering instead of a synonym map"

Same as V1's critique, now stronger. We have <500 items with LLM-extracted labels that have already been through a synonym map. Embeddings would add: a model dependency, a new failure mode, opaque cluster boundaries, and ~$0.05 of embedding cost — to cluster 89 unique labels that a YAML file handles in microseconds. If clustering quality is poor, add 5 entries to the YAML file. Don't reach for a sledgehammer.

### Bad Idea 4: "Fetch full comment trees for maximum data"

**Why it's tempting:** More data, more signal.

**Why it's bad:** Full comment trees are 80%+ noise: arguments about politics, tangential jokes, meta-discussion about the subreddit. `replace_more()` in PRAW is slow and rate-limit-hungry. A 200-comment thread has maybe 15 firsthand experience comments, all in the top 2 levels. Going deeper wastes API budget on garbage and inflates heuristic filter workload.

**Better alternative:** Posts + all top-level + filtered second-level. Captures ~90% of the signal at ~30% of the API cost.

### Bad Idea 5: "Let the LLM freely extract effects without evidence spans"

**Why it's tempting:** Simpler prompt, higher extraction "recall."

**Why it's bad:** "Higher recall" means "more hallucinated effects." An LLM reading "I felt weird on this drug" will happily extract `cognitive_impairment`, `derealization`, `malaise`, and `anxiety` — none of which the user said. Without evidence grounding, every extracted effect is unverifiable. The doctor reading the report cannot check whether "12 users reported cognitive impairment" means 12 people actually said that or the LLM inferred it from vague language 12 times.

**Better alternative:** Require `effect_evidence_span` as a literal text substring. Validate it post-extraction. Drop ungrounded effects. This reduces recall slightly but makes every extracted effect checkable.

---

## 19. Final Revised Recommendation

Build exactly this MVP. The V2 pipeline is:

1. **Query expansion** — YAML alias file, zero LLM
2. **Retrieval** — PRAW, posts + top-level comments + filtered second-level replies, subreddit allowlist, cached to JSONL, hard cap 500 items
3. **Heuristic pre-filter** — deterministic rules, no LLM, hard cap 400 items
4. **Hybrid firsthand classification** — heuristic regex signals computed before LLM call, LLM judgment inside extraction call, decision table resolution
5. **Grounded LLM extraction** — per-item, evidence spans required, validated post-extraction, hard cap 350 calls
6. **Deterministic normalization** — lowercase + strip + synonym YAML map, no LLM
7. **Deterministic aggregation** — grouping by canonical labels, nuanced conflict taxonomy (temporal, dose, direct, unresolved), principled example selection via scoring function
8. **LLM report generation** — one call from structured data (not raw text), hardcoded disclaimers, mandatory reliability section with visible metrics

V2 fixes V1's five real weaknesses: comments are first-class, normalization is deterministic, firsthand classification is hybrid, extraction is text-grounded, and contradiction detection is nuanced. The cost, complexity, and timeline are nearly identical to V1 (~$0.05-0.20/run, 5 pip dependencies, 1.5-2 day build). The system is still small, isolated, and disposable. No databases, no vector stores, no web frameworks, no agents.

The reliability section in every report means the doctor can see exactly how much data the tool found, how much it threw away, and where it's uncertain. That transparency is the difference between a useful tool and a dangerous one.
