# Reddit Medication Side-Effect Signal Tool — Design Plan v1

**Date:** 2026-04-02
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Type:** Separate side project. Not part of the main benchmark/LEG/code-generation research.
**Target:** 1-2 day MVP build

---

## 1. Executive Summary

A CLI tool that takes a medication name, retrieves relevant Reddit posts and comments, extracts structured first-person experience reports, aggregates them deterministically, and produces a Markdown report with anecdotal effect themes, contradictions, uncertainty notes, and raw example snippets. Every output is explicitly labeled as anecdotal and non-medical. The pipeline is: **query → retrieval → heuristic filtering → LLM extraction → deterministic aggregation → final summary generation**. No databases, no vector stores, no web frameworks in the MVP. Files in, files out, all cached to disk.

---

## 2. Scope and Non-Goals

### In scope (MVP)
- Single-drug query per run
- Reddit retrieval via PRAW (official API)
- Posts + top-level comments from configurable subreddit allowlist
- Heuristic + LLM-assisted filtering for first-person experience reports
- LLM-powered structured extraction of reported effects per post/comment
- Deterministic aggregation of extracted records into themed clusters
- Markdown report with disclaimers, themes, contradictions, raw examples, anecdotal counts
- Disk-cached raw retrieval and extracted records (JSONL)
- CLI interface
- Brand/generic name expansion via a small manually-curated alias file (not an LLM call)

### Non-goals
- Scientific validity, prevalence estimation, or pharmacovigilance claims
- Treatment recommendations or diagnostic output
- Real-time monitoring or alerting
- Multi-drug interaction analysis
- Sentiment analysis scores presented as meaningful
- Web UI (deferred to post-MVP)
- Embedding-based semantic search (not justified for MVP scale)
- Integration with the main repo's research pipeline, configs, logging, or prompt system

---

## 3. User Workflow

```
$ cd side_projects/reddit_med_signal
$ python -m reddit_med_signal "metformin"

[1/5] Resolving drug aliases: metformin → metformin, glucophage, fortamet
[2/5] Retrieving Reddit posts/comments (max 200 items)...
      Found 143 items across 5 subreddits. Cached to data/raw/metformin_20260402_183012.jsonl
[3/5] Filtering for first-person experience reports...
      87 of 143 items passed heuristic + LLM filter.
[4/5] Extracting structured effects from 87 items...
      Extracted 87 records. Cached to data/extracted/metformin_20260402_183012.jsonl
[5/5] Aggregating and generating report...
      Report written to reports/metformin_20260402_183012.md

Done. Total cost: ~$0.12 (gpt-4.1-nano, 87 extraction calls + 1 summary call)
```

The doctor opens the `.md` file. It has:
- A disclaimer header
- Top reported effect themes with anecdotal counts and raw examples
- Contradictory patterns called out explicitly
- Sparse-data warnings if applicable
- A "what this is NOT" footer

---

## 4. System Requirements

- Python 3.10+
- `praw` — Reddit API wrapper
- `openai` — LLM calls (OpenAI-compatible, could be swapped)
- `pydantic` — data validation for extracted records
- `pyyaml` — config
- `click` — CLI
- No other dependencies. No database. No Docker. No Redis. No queue.

Total new dependencies: 5 (praw, openai, pydantic, pyyaml, click). All are lightweight, well-maintained, and pip-installable.

---

## 5. Data Flow Design

```
                         ┌──────────────┐
                         │ Drug aliases  │ (YAML file, manually curated)
                         └──────┬───────┘
                                │
                   ┌────────────▼──────────────┐
 User input ──────▶  1. QUERY EXPANSION        │
 "metformin"       │  Resolve brand/generic     │
                   │  names from alias file     │
                   └────────────┬───────────────┘
                                │ ["metformin", "glucophage", ...]
                   ┌────────────▼───────────────┐
                   │  2. RETRIEVAL (PRAW)        │
                   │  Search allowed subreddits  │
                   │  Pull posts + top comments  │
                   │  Cache raw JSONL to disk    │
                   └────────────┬───────────────┘
                                │ [raw items]
                   ┌────────────▼───────────────┐
                   │  3. HEURISTIC FILTER        │
                   │  Drop: <30 chars, deleted,  │
                   │  bot accounts, memes,       │
                   │  non-English heuristic      │
                   └────────────┬───────────────┘
                                │ [candidate items]
                   ┌────────────▼───────────────┐
                   │  4. LLM EXTRACTION          │
                   │  Per-item structured extract │
                   │  → ExtractedRecord          │
                   │  Includes confidence flag    │
                   │  Cache extracted JSONL       │
                   └────────────┬───────────────┘
                                │ [ExtractedRecord list]
                   ┌────────────▼───────────────┐
                   │  5. DETERMINISTIC           │
                   │     AGGREGATION             │
                   │  Group by normalized effect  │
                   │  Count, deduplicate, detect  │
                   │  contradictions              │
                   └────────────┬───────────────┘
                                │ [AggregatedThemes]
                   ┌────────────▼───────────────┐
                   │  6. REPORT GENERATION       │
                   │  LLM summarizes themes      │
                   │  into readable Markdown      │
                   │  with mandatory disclaimers  │
                   │  + raw example snippets      │
                   └────────────┬───────────────┘
                                │
                           report.md
```

**Why this pipeline and not "LLM summarize raw posts":**

Raw Reddit text is noisy, contradictory, speculative, and repetitive. Dumping 200 posts into an LLM produces a hallucination-prone goulash that (a) loses individual attribution, (b) smooths over contradictions, (c) silently drops sparse signals, and (d) makes the output uncheckable. The structured pipeline preserves each individual claim as a checkable record, makes aggregation transparent and deterministic, and confines the LLM to two well-defined roles: extraction (per-item, auditable) and final prose generation (from pre-aggregated structured data, not raw text).

---

## 6. Module/Directory Plan

```
side_projects/
  reddit_med_signal/
    __main__.py              # CLI entry point
    cli.py                   # Click CLI definition
    config.py                # Load YAML config
    retrieval.py             # PRAW-based Reddit retrieval
    filtering.py             # Heuristic pre-filters
    extraction.py            # LLM-powered structured extraction
    aggregation.py           # Deterministic grouping + contradiction detection
    report.py                # LLM-powered Markdown report generation
    schemas.py               # Pydantic models (RawItem, ExtractedRecord, etc.)
    drug_aliases.py          # Load + resolve brand/generic aliases
    llm_client.py            # Thin wrapper for OpenAI calls with timeout + retry
    prompts/
      extraction.txt         # Extraction prompt template
      summarization.txt      # Report summarization prompt template
    config/
      default.yaml           # Default config (subreddits, limits, model, etc.)
      drug_aliases.yaml      # Brand/generic name mapping
    data/
      raw/                   # Cached raw Reddit payloads (JSONL)
      extracted/             # Cached extracted structured records (JSONL)
    reports/                 # Generated Markdown reports
    tests/
      __init__.py
      test_filtering.py
      test_extraction.py
      test_aggregation.py
      test_report.py
      test_schemas.py
      test_cli.py
      fixtures/
        raw_metformin_sample.jsonl
        extracted_metformin_sample.jsonl
        sparse_drug_sample.jsonl
        noisy_meme_sample.jsonl
    README.md
    requirements.txt
```

**Why `side_projects/reddit_med_signal/` and not `tools/`:**

`tools/` implies repo-wide utilities. This is a standalone project that happens to live in the same repo for convenience. `side_projects/` makes the isolation explicit. It has its own `requirements.txt`, its own `README.md`, and zero imports from the parent repo.

**Where things live:**
| Artifact | Location |
|----------|----------|
| Config | `config/default.yaml` |
| Drug aliases | `config/drug_aliases.yaml` |
| Raw Reddit cache | `data/raw/{drug}_{timestamp}.jsonl` |
| Extracted records cache | `data/extracted/{drug}_{timestamp}.jsonl` |
| Generated reports | `reports/{drug}_{timestamp}.md` |
| Prompt templates | `prompts/extraction.txt`, `prompts/summarization.txt` |
| Tests | `tests/` |

---

## 7. Detailed Component Design

### 7.1 Query Expansion (`drug_aliases.py`)

Loads `config/drug_aliases.yaml` which maps canonical names to known aliases:

```yaml
# config/drug_aliases.yaml
metformin:
  - glucophage
  - fortamet
  - riomet
  - glumetza
sertraline:
  - zoloft
bupropion:
  - wellbutrin
  - zyban
```

**Design decision: no LLM for alias resolution.** Drug name aliases are a closed, well-known set. An LLM would hallucinate aliases. A curated YAML file is correct, auditable, and zero-cost. The user can add entries as needed in 10 seconds.

The function returns a list of query strings:

```python
def resolve_aliases(drug_name: str, alias_map: dict) -> list[str]:
    """Return [canonical_name] + aliases. Case-insensitive lookup."""
    canonical = drug_name.lower().strip()
    aliases = alias_map.get(canonical, [])
    return [canonical] + [a.lower() for a in aliases]
```

If the drug is not in the alias file, the tool queries Reddit with just the user-provided name and logs a warning: "No alias expansion found for '{drug}'. Consider adding aliases to drug_aliases.yaml."

### 7.2 Retrieval (`retrieval.py`)

Uses PRAW to search Reddit. Design decisions:

**Decision 1: Posts + top-level comments, not full comment trees.** Full trees are expensive, slow, and dominated by tangential discussion. Top-level comments on relevant posts are the highest-signal source: they are typically direct responses that add personal experience or correct the OP.

**Decision 2: Subreddit allowlist.** Default allowlist in config:
```yaml
subreddits:
  - medication
  - AskDocs
  - Drugs
  - antidepressants
  - ADHD
  - bipolar
  - Nootropics
  - zoloft
  - lexapro
  - birthcontrol
  - PCOS
  - diabetes
  - Epilepsy
```

The user can override or extend via CLI flag or config edit. No blocklist needed in MVP — the allowlist IS the filter.

**Retrieval strategy:**
1. For each alias, search each subreddit with `subreddit.search(alias, sort="relevance", time_filter="year", limit=per_sub_limit)`
2. For each post returned, also fetch top N comments (configurable, default 5)
3. Deduplicate by Reddit ID (posts can appear in multiple alias searches)
4. Cache the entire retrieval to `data/raw/{drug}_{timestamp}.jsonl`

**Configurable limits:**
```yaml
retrieval:
  max_posts_per_subreddit: 25
  max_comments_per_post: 5
  time_filter: "year"    # all, year, month, week
  sort: "relevance"
  total_item_cap: 300    # hard cap across all subreddits
```

**Timeout:** Every PRAW call gets an explicit timeout via `praw.Reddit` config (`timeout=30`). If a subreddit is unreachable, log the error and continue to the next.

```python
@dataclass
class RawItem:
    item_type: str        # "post" | "comment"
    reddit_id: str        # t3_xxx or t1_xxx
    subreddit: str
    url: str
    author: str | None
    created_utc: float
    score: int
    title: str | None     # posts only
    body: str             # selftext for posts, body for comments
    parent_post_id: str | None  # comments only
```

### 7.3 Heuristic Filtering (`filtering.py`)

Fast, deterministic, no LLM calls. Goal: remove obvious junk before spending money on extraction.

**Filters applied in order:**

1. **Length filter:** Drop items with `len(body) < 30` characters. Too short to contain a useful experience report.
2. **Deleted/removed:** Drop if body is `[deleted]` or `[removed]`.
3. **Bot filter:** Drop if author matches known bot patterns (`AutoModerator`, accounts ending in `Bot`, accounts in a small hardcoded blocklist).
4. **URL-only:** Drop if body is >80% URLs (link dumps, not experience reports).
5. **Non-English heuristic:** Drop if >50% of words are not in a basic English word set. (Use a small set of ~1000 common English words as a rough check. This is a heuristic, not a classifier — it catches posts in other scripts/languages without expensive detection.)
6. **Meme/joke heuristic:** Drop if body matches common meme patterns (all-caps single line, copypasta signatures, "based", etc.). Keep this list short — false negatives are fine, false positives are not. When in doubt, keep the item.

**No LLM filtering in the heuristic stage.** The LLM extraction step (next) will assign a `firsthand_experience_confidence` score. Items that survive heuristic filtering but aren't genuine first-person reports will be caught there. This avoids paying for an LLM call on every item just to filter.

**Design decision: no upvote-based filtering.** Upvotes do not correlate with report quality or first-person experience. A detailed personal report about a rare side effect may have 2 upvotes. A joke about "Benadryl hat man" may have 4000. Upvotes are stored in the raw record for informational purposes but never used as a quality signal.

```python
def apply_heuristic_filters(items: list[RawItem]) -> list[RawItem]:
    """Return items that pass all heuristic filters. Log each drop reason."""
```

### 7.4 LLM Extraction (`extraction.py`)

This is the core value-add. One LLM call per filtered item. The LLM reads the Reddit text and produces a structured `ExtractedRecord`.

**Why per-item, not batch:** Per-item extraction is auditable (each record maps to exactly one source), parallelizable later, and produces consistent schema. Batch extraction loses attribution and makes the LLM more likely to merge or hallucinate across items.

**Model choice:** `gpt-4.1-nano` for extraction. It's cheap (~$0.001 per call), fast, and sufficient for structured extraction from short text. The extraction prompt is tightly constrained — this is not a creative task. Cost for 200 items: ~$0.20.

**What the LLM extracts per item:**

```python
class ExtractedRecord(BaseModel):
    drug_query: str
    canonical_drug_name: str
    source_type: Literal["post", "comment"]
    subreddit: str
    reddit_id: str
    url: str
    authored_timestamp: float
    text_excerpt: str                    # truncated to 500 chars
    firsthand_experience: bool           # LLM judgment: is this first-person use?
    firsthand_confidence: Literal["high", "medium", "low"]
    mentions_personal_use: bool
    reported_effects: list[ReportedEffect]
    co_medications: list[str]            # other drugs mentioned
    temporal_info: str | None            # "after 2 weeks", "immediately", etc.
    uncertainty_flags: list[str]         # e.g. "speculative", "secondhand", "unclear_causation"
    extraction_notes: str | None         # LLM's notes on ambiguity

class ReportedEffect(BaseModel):
    effect_raw: str                      # as stated: "made me nauseous"
    effect_normalized: str               # canonical: "nausea"
    directionality: Literal["positive", "negative", "neutral", "ambiguous"]
    severity_hint: Literal["mild", "moderate", "severe", "unspecified"]
    is_secondorder: bool                 # e.g. "lost appetite" → weight loss
    secondorder_chain: str | None        # e.g. "appetite_loss → weight_loss"
```

**Design decision: LLM does normalization during extraction.** Asking the LLM to both extract and normalize in a single call is efficient and avoids a separate normalization pass. The prompt provides a short normalization guide (see Section 11). Deterministic clustering in the aggregation step groups by `effect_normalized`, so the LLM's normalization choices are checkable and overridable.

**Design decision: no separate LLM filtering step.** The extraction prompt asks the LLM to set `firsthand_experience: false` for non-first-person items. The aggregation step drops these. This means we "waste" an extraction call on non-first-person items (~20% of filtered items), but the cost is trivial ($0.04 for 40 wasted calls) and we get the classification for free alongside extraction rather than paying for a separate filter call.

### 7.5 Deterministic Aggregation (`aggregation.py`)

No LLM calls in this stage. Pure Python logic operating on `ExtractedRecord` lists.

**Steps:**

1. **Drop non-firsthand:** Remove records where `firsthand_experience == False`.
2. **Group by `effect_normalized`:** Simple `defaultdict(list)` grouping.
3. **Count:** For each normalized effect, count occurrences. These are explicitly labeled "anecdotal mention count" in the report — never "prevalence" or "frequency."
4. **Detect contradictions:** If both "positive" and "negative" directionality exist for the same normalized effect (e.g., "weight_gain" and "weight_loss" both present, or "improved_mood" and "worsened_mood"), flag as contradictory.
5. **Detect second-order chains:** If `is_secondorder` is true, group the chains and note them.
6. **Deduplicate:** If the same `reddit_id` appears multiple times (shouldn't happen, but defensive), keep one.
7. **Co-medication frequency:** Count how often each co-medication appears alongside the queried drug.
8. **Uncertainty summary:** Aggregate `uncertainty_flags` across all records: how many are "speculative," "secondhand," etc.
9. **Sparse-data flag:** If total firsthand records < 10, flag the entire report as "sparse data — interpret with extreme caution."

```python
@dataclass
class EffectTheme:
    effect_normalized: str
    mention_count: int
    directionality_breakdown: dict[str, int]  # {"positive": 3, "negative": 7, "ambiguous": 2}
    severity_breakdown: dict[str, int]
    has_contradiction: bool
    secondorder_chains: list[str]
    example_excerpts: list[str]    # up to 3 raw text excerpts
    example_urls: list[str]        # corresponding URLs

@dataclass
class AggregationResult:
    drug_query: str
    canonical_drug_name: str
    total_raw_items: int
    total_after_filter: int
    total_firsthand: int
    is_sparse: bool
    themes: list[EffectTheme]           # sorted by mention_count desc
    contradictions: list[tuple[str, str]]  # pairs of contradicting effects
    co_medication_counts: dict[str, int]
    uncertainty_summary: dict[str, int]   # flag → count
    run_timestamp: str
```

**Design decision: deterministic clustering, not embedding-based.** For the MVP, grouping by `effect_normalized` string equality is sufficient. The LLM extraction step does the normalization work ("made me nauseous" → "nausea", "stomach was wrecked" → "nausea"). If normalization quality is poor in practice, a post-MVP step could add fuzzy matching (Levenshtein on normalized strings) or a small synonym map. Embeddings are overkill: we have <200 records with LLM-normalized labels, not 50,000 raw strings. If this assumption is wrong, the fix is a synonym YAML file, not a vector database.

### 7.6 Report Generation (`report.py`)

One LLM call. Input: the `AggregationResult` (serialized as JSON). Output: Markdown report.

**Model choice:** `gpt-4.1-mini` for the summary call. This is the only call that requires coherent prose generation. One call per run, so cost is negligible (~$0.02).

**The LLM does NOT see raw Reddit text.** It sees only the pre-aggregated `AggregationResult` JSON. This is critical: the LLM cannot hallucinate details that aren't in the aggregation, cannot merge records, and cannot silently drop contradictions. The aggregation step has already done the hard work.

**Mandatory report sections (enforced by prompt):**

1. Disclaimer header
2. Drug name and query details
3. Data summary (how many posts, subreddits, date range)
4. Top reported effects (with anecdotal counts and raw examples)
5. Contradictory patterns (explicitly called out)
6. Second-order effect chains (if any)
7. Co-medications frequently mentioned
8. Uncertainty and data quality notes
9. Sparse-data warning (if applicable)
10. "What this is NOT" footer

**Mandatory disclaimers (hardcoded in template, not generated by LLM):**

The disclaimer header and footer are NOT LLM-generated. They are hardcoded strings prepended and appended to the LLM's output. This ensures they cannot be omitted, softened, or rephrased by the model.

```python
DISCLAIMER_HEADER = """
> **IMPORTANT: This report is NOT medical advice.**
> It summarizes anecdotal reports from Reddit users. It has NOT been verified
> by medical professionals. Mention counts are NOT prevalence estimates.
> Correlation is NOT causation. Do NOT use this to make treatment decisions.
> Consult qualified medical professionals for any medical questions.
"""

DISCLAIMER_FOOTER = """
---
*This report was auto-generated from Reddit posts. It reflects what anonymous
internet users have written, not clinical evidence. Counts reflect how many
Reddit posts/comments mentioned an effect, not how common the effect actually
is. Many reported effects may be coincidental, misattributed, or fabricated.
This tool is for background situational awareness only.*
"""
```

### 7.7 LLM Client (`llm_client.py`)

Thin wrapper. No abstraction astronautics.

```python
def call_llm(
    prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    timeout: int = 30,
    response_format: dict | None = None,
) -> str:
    """Call OpenAI-compatible API. Raises on timeout or API error. No silent fallback."""
```

- Explicit timeout on every call (configurable, default 30s)
- Retry with exponential backoff: 3 attempts, base delay 2s
- Raises `LLMCallError` on exhausted retries — never silently returns empty
- Logs every call: model, token count, latency, cost estimate
- Uses `response_format={"type": "json_object"}` for extraction calls to enforce JSON output

---

## 8. LLM Usage Design

| Stage | LLM? | Model | Calls per run | Purpose |
|-------|-------|-------|---------------|---------|
| Query expansion | No | — | 0 | YAML lookup |
| Retrieval | No | — | 0 | PRAW API |
| Heuristic filtering | No | — | 0 | Deterministic rules |
| Extraction | Yes | gpt-4.1-nano | N (one per filtered item) | Structured extraction |
| Aggregation | No | — | 0 | Deterministic Python |
| Report generation | Yes | gpt-4.1-mini | 1 | Prose summary from structured data |

**Total LLM calls per run:** ~90-150 extraction calls + 1 summary call.
**Estimated cost per run:** $0.10-$0.25 depending on item count.

**What the LLM is NOT used for:**
- Drug name resolution (YAML file)
- Filtering (heuristics)
- Aggregation/counting (Python)
- Disclaimer text (hardcoded)
- Prevalence estimation (not done at all)
- Causality claims (not done at all)

---

## 9. Failure Modes and Defenses

### F1: Drug has very sparse Reddit discussion
- **Detection:** `total_firsthand < 10` after extraction
- **Defense:** Report includes explicit sparse-data warning. Aggregation still runs but themes are flagged as "based on <10 reports." CLI prints a warning.
- **Not done:** The tool does NOT broaden the search to unrelated subreddits or relax filters to manufacture volume. Sparse data is reported honestly.

### F2: Drug has ambiguous name / multiple meanings
- **Example:** "Plan B" (medication vs. idiom), "Ice" (methamphetamine vs. the word)
- **Defense:** The subreddit allowlist constrains to medical/health subreddits. The heuristic filter drops very short posts. The LLM extraction step evaluates whether the post is about the medication. Items where the LLM sets `firsthand_experience: false` or flags "unclear_drug_reference" in `uncertainty_flags` are excluded from aggregation.
- **Limitation:** Some false positives will remain. The report notes the drug name's ambiguity if the alias file includes an `ambiguous: true` flag.

### F3: Discussion dominated by jokes/memes/unrelated posts
- **Defense:** Heuristic filter catches obvious memes. LLM extraction catches subtler non-experience posts. Aggregation drops non-firsthand records. If >60% of retrieved items are dropped, the report includes a noise warning.

### F4: Comments contradict post author
- **Defense:** Posts and comments are extracted independently. If a comment says "that's not how metformin works, I've been on it for years and it does X," the comment is extracted as a separate firsthand report with its own effects. The aggregation step handles this naturally: contradictory effects appear in the contradiction detection.

### F5: Weight gain AND weight loss both common
- **Defense:** The aggregation contradiction detector explicitly looks for opposing directionalities on related effects. The report calls this out: "Both weight_gain (N=12) and weight_loss (N=8) were reported. This is a known pattern with [drug] and may reflect individual variation."

### F6: Second-order effects
- **Defense:** The extraction schema has `is_secondorder` and `secondorder_chain`. The LLM is prompted to identify these: "Did the user describe a chain of effects? For example, 'killed my appetite' leading to weight loss is appetite_loss → weight_loss." The aggregation step groups and reports chains separately.

### F7: Posts mention multiple medications
- **Defense:** The extraction schema has `co_medications`. The LLM lists all other drugs mentioned. The aggregation step reports co-medication frequency. The report includes a warning: "N reports mentioned concurrent use of other medications. Effects may not be attributable to [queried drug] alone."

### F8: Users speculate without firsthand experience
- **Defense:** `firsthand_experience` and `firsthand_confidence` fields. The LLM is explicitly prompted: "Is this person describing their own experience taking the medication, or are they speculating, giving advice, or reporting someone else's experience?" Low-confidence and non-firsthand items are excluded from theme aggregation but counted in the data summary.

### F9: Same anecdote in multiple reposts/quote chains
- **Defense:** Deduplication by `reddit_id` in retrieval. For semantic near-duplicates (same user posting the same story in multiple subreddits), the extraction step will produce similar `ExtractedRecord`s. The aggregation step could detect these via author+effect overlap, but for MVP, this is a known limitation noted in the report.

### F10: Reddit API rate limiting or downtime
- **Defense:** PRAW handles rate limiting automatically (sleeps when rate-limited). The tool has an explicit per-run timeout (configurable, default 5 minutes for retrieval). On timeout, it proceeds with whatever was retrieved and notes the incomplete retrieval in the report.

### F11: LLM returns malformed JSON
- **Defense:** `response_format={"type": "json_object"}` enforces valid JSON. Pydantic validation catches schema violations. On validation failure for a single item, log the error, skip the item, increment a `extraction_failures` counter. If >20% of items fail extraction, abort and report the error.

---

## 10. Logging, Caching, and Reproducibility

### Logging
- Python `logging` to stderr, not a custom framework
- Levels: INFO for pipeline progress, WARNING for skipped items / sparse data, ERROR for failures
- Every LLM call logs: model, prompt length, response length, latency, estimated cost

### Caching
- **Raw retrieval:** `data/raw/{drug}_{timestamp}.jsonl` — one JSON object per line, one line per `RawItem`
- **Extracted records:** `data/extracted/{drug}_{timestamp}.jsonl` — one JSON object per line, one line per `ExtractedRecord`
- **Cache reuse:** CLI flag `--from-cache {timestamp}` re-runs aggregation + report from cached extracted records without re-querying Reddit or re-calling the LLM. This is useful for re-running with different aggregation settings or regenerating the report.
- **No implicit cache:** The tool does NOT silently reuse old data. Every run without `--from-cache` queries Reddit fresh. This avoids stale-data confusion.

### Reproducibility
- Config is YAML, checked into the repo
- Prompt templates are files, checked into the repo
- LLM calls use `temperature=0.0` for extraction (deterministic-ish)
- Summary call uses `temperature=0.3` (some prose variation is acceptable)
- The report includes a metadata block at the bottom:
  ```
  Run: metformin_20260402_183012
  Config: default.yaml
  Model (extraction): gpt-4.1-nano
  Model (summary): gpt-4.1-mini
  Items retrieved: 143
  Items after filter: 87
  Items firsthand: 71
  Extraction failures: 2
  ```

---

## 11. Prompt Design Sketches

### Extraction Prompt (`prompts/extraction.txt`)

```
You are extracting structured information from a Reddit post or comment about a medication.

DRUG BEING QUERIED: {drug_name}
ALIASES: {aliases}

SOURCE TEXT:
---
{text}
---

Your task:
1. Determine if this is a FIRST-PERSON experience report (the author took or is taking the medication themselves).
2. If yes, extract all reported effects — positive, negative, neutral, or ambiguous.
3. Normalize each effect to a canonical short label (e.g., "nausea", "weight_gain", "improved_mood", "insomnia").
4. Note any second-order effect chains (e.g., "reduced appetite" leading to "weight loss").
5. List any other medications the author mentions taking concurrently.
6. Extract any temporal information (how long on the drug, when effects appeared).
7. Flag any uncertainty: is the author speculating? reporting hearsay? unclear if they actually took the drug?

NORMALIZATION GUIDE (use these labels when applicable):
- nausea, diarrhea, constipation, stomach_pain, appetite_increase, appetite_decrease
- weight_gain, weight_loss
- insomnia, drowsiness, fatigue, dizziness
- headache, brain_fog, improved_focus, anxiety_increase, anxiety_decrease
- mood_improvement, mood_worsening, emotional_blunting, irritability
- libido_increase, libido_decrease, sexual_dysfunction
- dry_mouth, sweating, rash, hair_loss
- no_effect, not_applicable

If the effect doesn't match any of these, create a short snake_case label.

Respond with a JSON object matching this exact schema:
{schema}

Be conservative. If uncertain whether this is first-person experience, set firsthand_confidence to "low". If you cannot determine the effect directionality, use "ambiguous". Do not infer effects that the author did not mention. Do not infer causation.
```

### Summarization Prompt (`prompts/summarization.txt`)

```
You are generating a structured Markdown report summarizing anecdotal Reddit reports about a medication.

IMPORTANT RULES:
- Every claim must be labeled as anecdotal. Never use words like "causes", "prevents", "treats".
- Use phrases like "users reported", "some commenters described", "anecdotal mentions suggest".
- Never state or imply prevalence. Say "N Reddit posts mentioned X" not "X is common" or "X occurs in N% of users".
- If contradictory effects exist, highlight them prominently. Do not resolve contradictions.
- If data is sparse (<10 firsthand reports), say so clearly and reduce confidence language.
- Include 1-2 raw example quotes per theme (provided in the data).
- Do not add information not present in the data below.
- Do not make treatment recommendations.
- Do not speculate about mechanisms.

AGGREGATED DATA:
{aggregation_json}

Generate a Markdown report with these sections:
1. ## Summary — 2-3 sentence overview of what Reddit users report
2. ## Most Frequently Mentioned Effects — table with effect, anecdotal count, directionality, example quote
3. ## Contradictory Patterns — any effects where users disagree
4. ## Second-Order Effect Chains — if any
5. ## Co-Medications Frequently Mentioned — list with counts
6. ## Data Quality Notes — uncertainty flags, extraction failures, sparse data warnings
```

### No clustering prompt needed in MVP

Clustering is deterministic via `effect_normalized` string matching. If normalization quality degrades in practice, the first fix is a synonym YAML file (`nausea: [nauseous, sick_to_stomach, queasy]`), not an LLM call.

---

## 12. Data Schemas

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
    retrieved_at: str              # ISO timestamp
```

### ExtractedRecord (extraction output)

```python
class ReportedEffect(BaseModel):
    effect_raw: str
    effect_normalized: str
    directionality: Literal["positive", "negative", "neutral", "ambiguous"]
    severity_hint: Literal["mild", "moderate", "severe", "unspecified"]
    is_secondorder: bool
    secondorder_chain: str | None

class ExtractedRecord(BaseModel):
    drug_query: str
    canonical_drug_name: str
    source_type: Literal["post", "comment"]
    subreddit: str
    reddit_id: str
    url: str
    authored_timestamp: float
    text_excerpt: str
    firsthand_experience: bool
    firsthand_confidence: Literal["high", "medium", "low"]
    mentions_personal_use: bool
    reported_effects: list[ReportedEffect]
    co_medications: list[str]
    temporal_info: str | None
    uncertainty_flags: list[str]
    extraction_notes: str | None
```

### AggregationResult (aggregation output)

```python
class EffectTheme(BaseModel):
    effect_normalized: str
    mention_count: int
    directionality_breakdown: dict[str, int]
    severity_breakdown: dict[str, int]
    has_contradiction: bool
    secondorder_chains: list[str]
    example_excerpts: list[str]   # up to 3
    example_urls: list[str]

class AggregationResult(BaseModel):
    drug_query: str
    canonical_drug_name: str
    total_raw_items: int
    total_after_filter: int
    total_firsthand: int
    is_sparse: bool
    themes: list[EffectTheme]
    contradictions: list[tuple[str, str]]
    co_medication_counts: dict[str, int]
    uncertainty_summary: dict[str, int]
    run_timestamp: str
    config_snapshot: dict         # frozen copy of config used
```

### Example Extracted Record (concrete)

```json
{
  "drug_query": "metformin",
  "canonical_drug_name": "metformin",
  "source_type": "comment",
  "subreddit": "diabetes",
  "reddit_id": "t1_abc123",
  "url": "https://reddit.com/r/diabetes/comments/xyz/slug/abc123",
  "authored_timestamp": 1711929600.0,
  "text_excerpt": "Been on metformin 500mg for about 3 months now. First two weeks were rough — constant nausea and diarrhea. That mostly went away but I still get stomach cramps if I take it without food. Lost about 8 pounds without trying, probably because I eat less to avoid the stomach issues.",
  "firsthand_experience": true,
  "firsthand_confidence": "high",
  "mentions_personal_use": true,
  "reported_effects": [
    {
      "effect_raw": "constant nausea",
      "effect_normalized": "nausea",
      "directionality": "negative",
      "severity_hint": "moderate",
      "is_secondorder": false,
      "secondorder_chain": null
    },
    {
      "effect_raw": "diarrhea",
      "effect_normalized": "diarrhea",
      "directionality": "negative",
      "severity_hint": "moderate",
      "is_secondorder": false,
      "secondorder_chain": null
    },
    {
      "effect_raw": "stomach cramps if I take it without food",
      "effect_normalized": "stomach_pain",
      "directionality": "negative",
      "severity_hint": "mild",
      "is_secondorder": false,
      "secondorder_chain": null
    },
    {
      "effect_raw": "Lost about 8 pounds without trying",
      "effect_normalized": "weight_loss",
      "directionality": "positive",
      "severity_hint": "moderate",
      "is_secondorder": true,
      "secondorder_chain": "appetite_decrease → weight_loss"
    }
  ],
  "co_medications": [],
  "temporal_info": "3 months; GI effects worst in first 2 weeks",
  "uncertainty_flags": [],
  "extraction_notes": "Weight loss attributed to eating less due to GI side effects — second-order chain."
}
```

---

## 13. Rate Limits, Cost, and Operational Constraints

### Reddit API
- PRAW respects Reddit's rate limits automatically (60 requests/minute for OAuth)
- A typical run makes ~30-50 API calls (search + comment fetches)
- Retrieval phase: ~30-60 seconds
- **Requirement:** Reddit API credentials (client_id, client_secret, user_agent). Stored in environment variables, NOT in config files.

### LLM API
- Extraction: ~100 calls × ~500 input tokens × ~300 output tokens = ~80K total tokens
- Summary: 1 call × ~3K input tokens × ~1K output tokens = ~4K total tokens
- **gpt-4.1-nano cost:** ~$0.10/M input, ~$0.40/M output → extraction ≈ $0.02 input + $0.012 output ≈ $0.03
- **gpt-4.1-mini cost:** ~$0.40/M input, ~$1.60/M output → summary ≈ $0.001 + $0.002 ≈ $0.003
- **Total cost per run: ~$0.05-$0.15**
- Rate limits: gpt-4.1-nano has high RPM limits; no issue for 100 serial calls

### Operational constraints
- **Single-process, serial execution.** No parallelism in MVP. Extraction calls are serial (one at a time). A run with 100 items takes ~3-5 minutes total.
- **No background jobs.** Run it, wait, read the report.
- **Disk space:** ~1MB per run (raw + extracted + report). Negligible.

---

## 14. Privacy, Safety, and UX Guardrails

### Privacy
- **No PII storage beyond Reddit usernames** (which are public). The tool stores author usernames from public Reddit posts for deduplication. It does not store or process any patient data, medical records, or private information.
- **Reddit content is public.** Cached posts are publicly available text. However, the `data/` directory should be gitignored to avoid accidentally committing cached Reddit content to the repo.

### Safety guardrails
- **Hardcoded disclaimers** (not LLM-generated) appear at the top and bottom of every report. See Section 7.6.
- **No treatment language.** The summarization prompt explicitly prohibits "causes," "prevents," "treats," and treatment recommendations.
- **No prevalence claims.** Counts are always qualified as "N Reddit posts mentioned" not "N% of patients experience."
- **No causation claims.** The extraction prompt sets `uncertainty_flags` to include "unclear_causation" when the user doesn't establish a clear temporal relationship.
- **Sparse-data warning.** Reports with <10 firsthand records get a prominent warning.

### UX guardrails
- The CLI prints a one-line disclaimer on every run: "This tool provides anecdotal summaries from Reddit. Not medical advice."
- The report is Markdown, not a polished clinical document. The format explicitly communicates "rough working notes," not "authoritative reference."

### .gitignore additions
```
side_projects/reddit_med_signal/data/
side_projects/reddit_med_signal/reports/
```

---

## 15. Phased Implementation Plan

### Phase 1: Skeleton + Retrieval (2-3 hours)
- Create directory structure
- Implement `schemas.py` (all Pydantic models)
- Implement `config.py` (load YAML)
- Implement `drug_aliases.py` (alias resolution)
- Implement `retrieval.py` (PRAW search + comment fetch + cache to JSONL)
- Implement `llm_client.py` (thin OpenAI wrapper with timeout/retry)
- Write `config/default.yaml` and `config/drug_aliases.yaml` with 10-15 common drugs
- **Test:** Run retrieval for "metformin", verify JSONL output

### Phase 2: Filtering + Extraction (2-3 hours)
- Implement `filtering.py` (all heuristic filters)
- Implement `extraction.py` (per-item LLM extraction)
- Write `prompts/extraction.txt`
- **Test:** Run extraction on cached metformin data, verify ExtractedRecord output
- Write fixture-based tests for extraction with mock LLM responses

### Phase 3: Aggregation + Report (2-3 hours)
- Implement `aggregation.py` (grouping, counting, contradiction detection)
- Implement `report.py` (LLM summary + hardcoded disclaimers)
- Write `prompts/summarization.txt`
- **Test:** Run full pipeline, verify Markdown report
- Write aggregation tests for contradictory effects, sparse data, co-medications

### Phase 4: CLI + Polish (1-2 hours)
- Implement `cli.py` (Click CLI with flags)
- Implement `__main__.py`
- Add `--from-cache` flag
- Add `--subreddits` override flag
- Add `--max-items` flag
- Add cost summary to CLI output
- Final integration test: full pipeline from CLI

### Phase 5: Testing + Documentation (1-2 hours)
- Write remaining unit tests
- Create test fixtures for sparse data, noisy data, multi-drug mentions
- Write `README.md` with setup instructions
- Verify `.gitignore` excludes `data/` and `reports/`

**Total estimated time: 8-13 hours across 1-2 days.**

---

## 16. Test Plan

### Unit tests

**`test_filtering.py`:**
- `test_short_text_dropped`: Items with <30 chars are filtered
- `test_deleted_dropped`: `[deleted]` and `[removed]` items are filtered
- `test_bot_dropped`: AutoModerator and `*Bot` authors are filtered
- `test_url_only_dropped`: Posts that are >80% URLs are filtered
- `test_valid_item_passes`: A normal experience report passes all filters
- `test_meme_heuristic`: Known meme patterns are caught

**`test_extraction.py`:**
- `test_firsthand_positive`: Clear first-person report is extracted correctly
- `test_secondhand_excluded`: "My friend takes..." gets `firsthand_experience: false`
- `test_multiple_effects`: Post with 3 effects produces 3 `ReportedEffect` entries
- `test_secondorder_chain`: "Lost appetite so lost weight" produces correct chain
- `test_co_medications`: "I also take Wellbutrin" populates `co_medications`
- `test_speculation_flagged`: "I think it might cause..." gets `uncertainty_flags: ["speculative"]`
- `test_malformed_llm_response`: Invalid JSON from LLM raises, doesn't silently pass
- All extraction tests use fixture LLM responses (mocked), not live API calls

**`test_aggregation.py`:**
- `test_basic_grouping`: 5 nausea records → EffectTheme with count=5
- `test_contradiction_detection`: weight_gain + weight_loss → flagged
- `test_sparse_flag`: <10 firsthand records → `is_sparse=True`
- `test_non_firsthand_excluded`: Records with `firsthand_experience=False` excluded from themes
- `test_co_medication_counts`: Co-medications counted correctly
- `test_deduplication`: Duplicate reddit_ids collapsed
- `test_empty_input`: Zero records → AggregationResult with is_sparse=True, empty themes

**`test_report.py`:**
- `test_disclaimer_present`: Header and footer disclaimers appear in every report
- `test_sparse_warning`: Sparse data warning appears when is_sparse=True
- `test_contradiction_section`: Contradictions are rendered in the report
- `test_no_prevalence_language`: Report does not contain "common", "frequent", "% of users", "prevalence"
- `test_no_treatment_language`: Report does not contain "recommend", "should take", "prescribe"

**`test_schemas.py`:**
- `test_extracted_record_validation`: Valid JSON parses into ExtractedRecord
- `test_invalid_directionality`: Invalid enum value raises ValidationError
- `test_raw_item_roundtrip`: RawItem → JSON → RawItem is lossless

**`test_cli.py`:**
- `test_basic_run`: CLI runs without error on cached fixture data
- `test_from_cache_flag`: `--from-cache` skips retrieval and extraction
- `test_unknown_drug_warning`: Unlisted drug prints alias warning

### Test fixtures (`tests/fixtures/`)
- `raw_metformin_sample.jsonl`: 20 raw items (mix of posts and comments)
- `extracted_metformin_sample.jsonl`: 15 extracted records (mix of firsthand and secondhand)
- `sparse_drug_sample.jsonl`: 3 extracted records (triggers sparse-data path)
- `noisy_meme_sample.jsonl`: 10 raw items dominated by jokes/memes

---

## 17. Example CLI/API Shapes

### Basic run
```bash
$ python -m reddit_med_signal "sertraline"
```

### With options
```bash
$ python -m reddit_med_signal "sertraline" \
    --max-items 100 \
    --subreddits "zoloft,antidepressants,AskDocs" \
    --time-filter month \
    --config config/default.yaml
```

### Re-run from cache
```bash
$ python -m reddit_med_signal "sertraline" --from-cache 20260402_183012
```

### Output
```
[reddit_med_signal] Drug: sertraline (aliases: zoloft)
[reddit_med_signal] This tool provides anecdotal summaries from Reddit. Not medical advice.
[reddit_med_signal] [1/5] Resolving aliases: sertraline → sertraline, zoloft
[reddit_med_signal] [2/5] Retrieving from 5 subreddits (max 200 items)...
[reddit_med_signal]   r/zoloft: 25 posts, 47 comments
[reddit_med_signal]   r/antidepressants: 18 posts, 22 comments
[reddit_med_signal]   ...
[reddit_med_signal]   Total: 156 items (cached: data/raw/sertraline_20260402_190511.jsonl)
[reddit_med_signal] [3/5] Heuristic filtering: 156 → 112 items (44 dropped)
[reddit_med_signal] [4/5] Extracting structured effects (112 LLM calls)...
[reddit_med_signal]   Progress: 112/112 [====================] 100%
[reddit_med_signal]   Firsthand reports: 89 of 112
[reddit_med_signal]   Extraction failures: 1
[reddit_med_signal]   Cached: data/extracted/sertraline_20260402_190511.jsonl
[reddit_med_signal] [5/5] Aggregating and generating report...
[reddit_med_signal]   Report: reports/sertraline_20260402_190511.md
[reddit_med_signal]
[reddit_med_signal] Cost: ~$0.08 (112 extraction calls + 1 summary call)
[reddit_med_signal] Done.
```

### Example Report Shape (abbreviated)

```markdown
> **IMPORTANT: This report is NOT medical advice.**
> It summarizes anecdotal reports from Reddit users. [... full disclaimer ...]

# Sertraline (Zoloft) — Anecdotal Reddit Report

**Generated:** 2026-04-02 19:05
**Sources:** 89 first-person reports from 156 retrieved items across 5 subreddits
**Time range:** Past year
**Data quality:** Adequate (89 firsthand reports, 1 extraction failure)

## Most Frequently Mentioned Effects

| Effect | Mentions | Direction | Example |
|--------|----------|-----------|---------|
| nausea | 34 | negative | *"First week was brutal, couldn't eat anything without feeling sick"* |
| insomnia | 28 | negative | *"Wide awake at 3am every night for the first month"* |
| anxiety_decrease | 24 | positive | *"After about 3 weeks the constant worry just... stopped"* |
| sexual_dysfunction | 21 | negative | *"Zero libido, like a light switch turned off"* |
| drowsiness | 18 | negative | *"Couldn't stay awake past 8pm"* |
| mood_improvement | 16 | positive | *"I finally feel like myself again after years of depression"* |
| weight_gain | 12 | negative | *"Put on 15 pounds in 4 months"* |
| emotional_blunting | 11 | negative | *"I'm not sad anymore but I'm not happy either"* |

## Contradictory Patterns

- **drowsiness (18) vs. insomnia (28):** Both commonly reported. Multiple users noted
  insomnia in the first weeks transitioning to drowsiness later. This may reflect
  temporal variation rather than genuine contradiction.
- **weight_gain (12) vs. weight_loss (4):** Both reported. Weight loss reports were
  typically in the first 1-2 months; weight gain reports were in longer-term users (3+ months).

## Second-Order Effect Chains

- nausea → appetite_decrease → weight_loss (4 mentions)
- emotional_blunting → libido_decrease (3 mentions)

## Co-Medications Frequently Mentioned

- bupropion (Wellbutrin): 14 mentions
- trazodone: 8 mentions
- buspirone: 6 mentions

## Data Quality Notes

- 23 items flagged as "speculative" (author was not certain about cause)
- 12 items flagged as "secondhand" (reporting someone else's experience) — excluded from counts above
- 1 extraction failure (malformed LLM response, item skipped)
- Drug name "Zoloft" is unambiguous — no name-confusion concerns

---
*This report was auto-generated from Reddit posts. [... full footer disclaimer ...]*

<!-- Run: sertraline_20260402_190511 | Config: default.yaml | Models: gpt-4.1-nano (extraction), gpt-4.1-mini (summary) | Items: 156 raw, 112 filtered, 89 firsthand, 1 failed -->
```

---

## 18. Harsh Review: 5 Tempting Bad Ideas

### Bad Idea 1: "Just summarize all retrieved text directly"

**Why it's tempting:** One LLM call, instant output, zero pipeline complexity.

**Why it's bad:** The LLM will (a) silently merge contradictory reports into a smooth narrative, (b) lose individual attribution so nothing is checkable, (c) hallucinate frequency language ("many users report...") from a small sample, (d) drop rare effects in favor of common ones, (e) fail to distinguish first-person experience from speculation. The output looks polished but is unverifiable. You cannot point to which Reddit post said what.

**Better alternative:** The pipeline in this plan: extract per-item, aggregate deterministically, then summarize from structured data. Every claim maps to a source.

### Bad Idea 2: "Use a vector database for semantic search"

**Why it's tempting:** "Embeddings find similar content!" Sounds sophisticated.

**Why it's bad:** We have <300 items per run. A `defaultdict(list)` grouping on LLM-normalized labels does the same job in 0.1ms with zero infrastructure. A vector DB adds setup cost, operational complexity, embedding model dependency, and a new failure mode — all to search a list that fits in memory. Embeddings also make clustering opaque: why did these two effects cluster together? With normalized labels, it's transparent.

**Better alternative:** Deterministic grouping on `effect_normalized`. If normalization quality is poor, add a synonym YAML file.

### Bad Idea 3: "Scrape the whole subreddit history"

**Why it's tempting:** More data = better results, right?

**Why it's bad:** (a) Violates Reddit ToS and API rate limits, (b) produces thousands of items that are mostly irrelevant, (c) makes extraction cost prohibitive ($10+ per run), (d) old posts may reference discontinued formulations or outdated information, (e) the doctor wants a quick sense of recent discussion, not an exhaustive literature review.

**Better alternative:** Time-bounded search (past year) with configurable limits. 200-300 items is plenty for a first-pass signal.

### Bad Idea 4: "Trust upvote counts as quality signals"

**Why it's tempting:** Upvotes seem like crowd-sourced quality assessment.

**Why it's bad:** High-upvote posts are funny, dramatic, or early. A detailed, accurate first-person report about a rare side effect gets 3 upvotes. A joke about Ambien sleepwalking gets 5000. Filtering by upvotes would systematically exclude the most valuable content (specific, detailed, less popular) and promote the least valuable (entertaining, vague, widely relatable).

**Better alternative:** Ignore upvotes for filtering. Store them in RawItem for informational purposes only.

### Bad Idea 5: "Let the model infer prevalence from mention counts"

**Why it's tempting:** "34 of 89 users mentioned nausea, so ~38% experience nausea."

**Why it's bad:** Reddit is not a clinical trial. The sample is self-selected (people with side effects are more likely to post), biased by subreddit culture, affected by post visibility, and not controlled for dosage, duration, comorbidities, or concurrent medications. Reporting 38% implies a measurement that doesn't exist. It creates false precision that a doctor might unconsciously weight as evidence.

**Better alternative:** Report raw anecdotal counts with explicit qualifiers: "34 Reddit posts mentioned nausea." Never compute percentages. Never say "common" or "rare." Let the doctor interpret the counts knowing they are Reddit posts, not clinical data.

---

## 19. Final Recommendation

Build exactly this MVP. The pipeline is:

1. **Query expansion** — YAML alias file, zero LLM
2. **Retrieval** — PRAW, posts + top comments, subreddit allowlist, cached to JSONL
3. **Heuristic filtering** — deterministic rules, no LLM
4. **LLM extraction** — per-item structured extraction into `ExtractedRecord`, cached to JSONL
5. **Deterministic aggregation** — grouping, counting, contradiction detection, pure Python
6. **LLM report generation** — one call from structured data, hardcoded disclaimers

No database. No vector store. No web UI. No embeddings. No microservices. No Docker. CLI in, Markdown out, everything cached to disk.

The tool is honest about what it is: a structured reader of Reddit anecdotes. It adds value through organization, deduplication, contradiction detection, and transparency — not through false authority. Every claim in the report traces to specific Reddit posts. Every count is labeled as anecdotal. Every disclaimer is hardcoded, not LLM-generated.

Build Phase 1-4 sequentially. Each phase produces a testable artifact. The doctor can start using it after Phase 4 (~8 hours of implementation).
