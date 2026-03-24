# T3 Benchmark — Standalone Repo Extraction Plan

**Date:** 2026-03-23
**Source:** `/Users/vskarich/repos/cs372research_2/cs372research/`
**Target:** `T3_code_generation_MVP/` → new standalone repo

---

## 1. Dependency Graph

### A. Internal Imports (within T3_code_generation_MVP)

All imports form a clean DAG with no cycles:

```
runner.py
  └── execution.py
        ├── llm.py → parse.py, llm_mock.py
        ├── evaluator.py → eval_cases.py
        ├── prompts.py
        ├── nudges/router.py → nudges/core.py → nudges/operators.py
        │                    → nudges/mapping.py
        ├── scm_prompts.py → scm_data.py
        ├── reasoning_prompts.py
        ├── contract.py
        └── diff_gate.py
  └── retry_harness.py
        ├── llm.py
        ├── parse.py
        ├── evaluator.py
        └── prompts.py

exec_eval.py (called by evaluator.py)
  └── parse.py
```

**Cross-repo imports: ZERO.** No imports from multi_agent, eval, logging_v2, agent_audit, agents, models, simulation, or any sibling directory.

### B. External Package Dependencies

| Package | Used By | Required |
|---|---|---|
| `openai` | llm.py (conditional) | Optional — mock fallback if no API key |
| `pytest` | tests/ | Dev only |

**That's it.** Everything else is Python stdlib (json, re, pathlib, logging, importlib, difflib, concurrent.futures, math, collections, time, types, argparse).

### C. Runtime Dependencies

| Dependency | Location | Required |
|---|---|---|
| `OPENAI_API_KEY` env var | llm.py:34 | Optional — falls back to llm_mock.py |
| `cases.json` | repo root | Required — case definitions |
| `cases_v2.json` | repo root | Required — v2 case definitions |
| `code_snippets/` | 74 files across subdirs | Required — buggy source code |
| `code_snippets_v2/` | ~160 files | Required — v2 buggy code |
| `reference_fixes/` | 46 files | Required — correct fixes |
| Python ≥ 3.11 | type hints use `X | None` syntax | Required |
| `logs/` directory | created at runtime | Auto-created by init_run_log() |

---

## 2. Required File List

### Core Code (MUST include)

```
runner.py
execution.py
llm.py
llm_mock.py
parse.py
evaluator.py
eval_cases.py
exec_eval.py
contract.py
diff_gate.py
prompts.py
reasoning_prompts.py
scm_prompts.py
scm_data.py
retry_harness.py
validate_cases_v2.py
nudges/__init__.py
nudges/core.py
nudges/operators.py
nudges/mapping.py
nudges/router.py
```

### Data Files (MUST include)

```
cases.json
cases_v2.json
code_snippets/          (entire tree — 74 files)
code_snippets_v2/       (entire tree — ~160 files)
reference_fixes/        (entire tree — 46 files)
```

### Tests (SHOULD include)

```
tests/                  (16 test files)
tests_v2/              (13 test files)
```

### Scripts (SHOULD include)

```
scripts/run_tests.sh
scripts/run_ablation.sh
scripts/extract_responses.py
scripts/extract_metadata.py
scripts/test_invariant.py
```

### Documentation (OPTIONAL — include for context)

```
analysis/               (forensic reports, REI analysis)
plan/                   (experiment plans)
ABLATION_RESULTS.md
FORENSIC_ANALYSIS_20260323.md
```

### MUST CREATE (new files for standalone repo)

```
pyproject.toml          (minimal — see below)
README.md
.gitignore
.env.example
```

### MUST NOT Include

```
logs/                   (runtime artifacts — regenerated)
__pycache__/
.venv/
deep_research_reports/  (large PDFs, not code)
```

---

## 3. Missing Dependency Issues + Fixes

### Issue 1: `.clog/` Does Not Exist

**Problem:** The extraction spec mentions `.clog/` but this directory does not exist anywhere in the repo.

**Fix:** Skip. T3 uses its own `logs/` directory with JSONL files. No `.clog/` integration needed.

### Issue 2: `dashboard/` Lives Outside T3 and Has Separate Dependencies

**Problem:** `tools/dashboard/` exists in the parent repo. It depends on FastAPI, references `logs/prompt_traces.jsonl` and `logging/runs` — these are from the broader debate system, NOT T3.

**Fix:** Do NOT extract the dashboard as-is. Two options:
- **Option A (recommended):** Skip dashboard entirely. T3 analysis is done via scripts (`scripts/extract_metadata.py`, `scripts/shadow_analysis.py`) and markdown reports.
- **Option B:** Create a minimal T3-specific dashboard later that reads from `logs/*.jsonl`. This would be a new component, not a port.

### Issue 3: `pyproject.toml` References Other Projects

**Problem:** Parent `pyproject.toml` has testpaths for multi_agent, eval, etc. and 25+ dependencies T3 doesn't use.

**Fix:** Create new minimal `pyproject.toml`:

```toml
[project]
name = "t3-code-generation-benchmark"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
api = ["openai>=1.0.0"]
dev = ["pytest>=8.0.0"]

[tool.pytest.ini_options]
testpaths = ["tests", "tests_v2"]
addopts = "--tb=short -q"
```

### Issue 4: `.venv` Path Hardcoded in Scripts

**Problem:** `scripts/run_tests.sh` and `scripts/run_ablation.sh` reference `../.venv/bin/python` (relative to T3_code_generation_MVP, pointing at the parent venv).

**Fix:** Update scripts to use `python` (assuming venv is activated) or detect venv location:
```bash
PYTHON="${VIRTUAL_ENV:-$(pwd)/.venv}/bin/python"
```

### Issue 5: Test `sys.path` Manipulation

**Problem:** All test files do `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`. This works because tests are in `tests/` which is one level below the code. In a standalone repo, this still works as-is.

**Fix:** None needed — the pattern is self-relative and portable.

---

## 4. Refactor Plan (Minimal)

| Change | Why | Effort |
|---|---|---|
| Create `pyproject.toml` | Standalone dependency management | 1 file |
| Update `scripts/*.sh` to use portable Python path | Remove parent venv coupling | 2 files, 1 line each |
| Create `.env.example` with `OPENAI_API_KEY=sk-your-key` | Document runtime dependency | 1 file |
| Create `README.md` with install + run instructions | Onboarding | 1 file |
| Create `.gitignore` | Exclude logs, pycache, venv | 1 file |

**No code changes to .py files needed.** The codebase is already self-contained.

---

## 5. Proposed Repo Structure

```
t3-code-generation-benchmark/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── runner.py                    # CLI entry point
├── execution.py                 # Core execution + logging
├── retry_harness.py             # Trajectory-level retry probe
├── llm.py                       # LLM API wrapper + mock fallback
├── llm_mock.py                  # Deterministic mock responses
├── parse.py                     # Response parsing (JSON + fallbacks)
├── evaluator.py                 # Evaluation dispatcher
├── eval_cases.py                # Case-specific heuristic evaluators
├── exec_eval.py                 # Execution-based evaluation
├── contract.py                  # Contract-gated execution
├── diff_gate.py                 # Contract diff validation
├── prompts.py                   # Prompt templates + nudge library
├── reasoning_prompts.py         # Reasoning interface builders
├── scm_prompts.py               # SCM evidence prompt builders
├── scm_data.py                  # SCM evidence data registry
├── validate_cases_v2.py         # Case validation utility
│
├── cases.json                   # 37 benchmark cases (v1)
├── cases_v2.json                # v2 benchmark cases
│
├── nudges/                      # Nudge operator system
│   ├── __init__.py
│   ├── core.py
│   ├── operators.py
│   ├── mapping.py
│   └── router.py
│
├── code_snippets/               # Buggy source code (v1, 74 files)
├── code_snippets_v2/            # Buggy source code (v2, ~160 files)
├── reference_fixes/             # Known-correct fixes (46 files)
│
├── tests/                       # Unit + integration tests (v1)
├── tests_v2/                    # Tests for v2 cases
│
├── scripts/
│   ├── run_tests.sh
│   ├── run_ablation.sh
│   ├── extract_responses.py
│   ├── extract_metadata.py
│   ├── test_invariant.py
│   └── shadow_analysis.py       # Post-hoc retry comparison
│
├── analysis/                    # Generated reports (optional)
│   ├── ABLATION_RESULTS.md
│   ├── FORENSIC_ANALYSIS_20260323.md
│   └── REI_DEEP_ANALYSIS.md
│
├── plan/                        # Experiment plans (optional)
│
└── logs/                        # Runtime output (gitignored)
```

---

## 6. Reproducibility Checklist

### Install

```bash
git clone <new-repo-url>
cd t3-code-generation-benchmark
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"            # pytest
pip install -e ".[api]"            # openai (optional)
```

### Environment Variables

```bash
cp .env.example .env
# Edit .env to add your OpenAI API key (optional — mock works without it)
export OPENAI_API_KEY=sk-your-key
```

### Run Tests (No API Key Needed)

```bash
pytest tests/ -v                   # 234+ tests, all use mock LLM
pytest tests_v2/ -v                # v2 case tests
```

### Run a Single Case (Requires API Key)

```bash
python runner.py --model gpt-4o-mini --conditions baseline --case-id alias_trivial --parallel 1
```

### Run Full Ablation

```bash
python runner.py --model gpt-4o-mini --conditions baseline,retry_no_contract --parallel 6
```

### Verify Logs

```bash
python scripts/extract_metadata.py logs/gpt-4o-mini_*.jsonl
```

---

## 7. Validation Plan

After extraction, verify:

### Step 1: Tests pass in isolation

```bash
cd t3-code-generation-benchmark/
python -m venv .venv && source .venv/bin/activate
pip install pytest
pytest tests/ -v
# Expected: 234+ pass, 0 fail
```

### Step 2: Mock run works

```bash
OPENAI_API_KEY=sk-dummy python runner.py --model gpt-4o-mini --conditions baseline --case-id alias_trivial
# Expected: completes, produces logs/gpt-4o-mini_*.jsonl
```

### Step 3: Logs are written correctly

```bash
python scripts/extract_metadata.py logs/gpt-4o-mini_*.jsonl
# Expected: structured output with pass/fail, score, invariant results
```

### Step 4: No import errors

```bash
python -c "import runner; import execution; import retry_harness; import evaluator; import exec_eval; print('All imports OK')"
```

### Step 5: Real API (optional)

```bash
export OPENAI_API_KEY=sk-real-key
python runner.py --model gpt-4o-mini --conditions baseline,retry_no_contract --case-id alias_trivial --parallel 1
# Expected: real API calls, retry trajectory in logs
```

---

## Summary

**Extraction difficulty: LOW.** T3_code_generation_MVP has:
- **0** imports from parent repo
- **0** hidden config dependencies
- **1** optional external package (openai)
- **~300 files** to copy (code + data + tests)

The only work needed is 4 new files (pyproject.toml, README.md, .env.example, .gitignore) and updating 2 script paths. No Python code changes required.
