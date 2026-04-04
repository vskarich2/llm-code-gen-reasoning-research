# File Reorganization Plan — v4

**Supersedes:** file_reorganization_plan_v3.md
**Type:** v3 code architecture + artifact hygiene cleanup
**Logic changes:** ZERO
**Date:** 2026-04-02

---

## Changes from v3

v3 was correct on code architecture. v4 adds one thing: **artifact directory consolidation**.

8 non-code directories currently at root are moved under `artifacts/`. `reference_fixes/` moves to `data/reference_fixes/` (ground truth data used by preflight validation, not a generated artifact). `evaluators/` stays at root (importable Python code). `assembly/` is dead code and archived. `rules/` stays at root (system control plane). `nudges/` stays at root (runtime code imported by condition_registry and execution).

---

## 1. Artifact Move Plan

### SAFE TO MOVE (0 code references)

```
plans/                  → artifacts/plans/
docs/                   → artifacts/docs/
analysis_output/        → artifacts/analysis_output/
deep_research_reports/  → artifacts/deep_research_reports/
auto_plans/             → artifacts/auto_plans/
experiments/            → artifacts/experiments/
_archive/               → artifacts/_archive/
```

### MOVE WITH PATH UPDATES (code references exist)

```
audits/                 → artifacts/audits/
```
**Impact:** 2 scripts reference `audits/` as output dirs:
- `scripts/run_oracle_eval.py:356` — default output dir `audits/oracle_eval`
- `scripts/run_oracle_intervention.py:231` — default output dir `audits/oracle_intervention`
Update both default paths to `artifacts/audits/oracle_eval` and `artifacts/audits/oracle_intervention`.

```
reference_fixes/        → data/reference_fixes/
```
**Impact:** `preflight_check.py:92` resolves `BASE / "reference_fixes" / f"{cid}.py"`. After the code reorg (v3), this becomes `orchestration/preflight_check.py` using `PROJECT_ROOT`. Update the path string to `"data/reference_fixes"`.
**Rationale:** `reference_fixes/` contains ground truth reference implementations used by preflight validation. It is NOT a generated artifact — it is validation data. It belongs alongside case definitions in `data/`.

### DO NOT MOVE

| Directory | Reason |
|---|---|
| `evaluators/` | Contains importable Python (`evaluators.reasoning_truth`), used by 2 scripts. Stays at root. |
| `assembly/` | Dead package (empty `__init__.py`, no imports). Move to `artifacts/_archive/assembly/`. |
| `logs/` | Runtime output, used by execution system. Stays at root. |
| `code_snippets/` | Runtime data — case code files loaded by runner. Stays at root. |
| `code_snippets_v2/` | Same — runtime data. Stays at root. |
| `rules/` | System control plane — LLM behavioral constraints consumed via CLAUDE.md. NOT an artifact. Stays at root. |
| `nudges/` | **Runtime code** — imported by `condition_registry.py` and `execution.py`. Contains Python modules (`core.py`, `mapping.py`, `operators.py`, `router.py`). NOT an artifact. Stays at root. |

### Special Case: rules/

`rules/` is NOT an artifact. It is part of the system control plane (LLM execution constraints). It must remain at root to:
- maintain clear separation from generated outputs
- avoid accidental deletion during artifact cleanup
- support future programmatic enforcement
- preserve CLAUDE.md path stability (CLAUDE.md references `rules/` and is loaded automatically)

### Special Case: nudges/

`nudges/` is NOT an artifact. It is **runtime code** imported by `condition_registry.py` (line 244, 279) and `execution.py` (line 15, 118). It contains Python modules: `core.py`, `mapping.py`, `operators.py`, `router.py`.

**Rule:** If nudges are reused across runs or referenced by prompt assembly, they MUST stay at root (or move to `pipeline/` during the v3 code reorg). They must NEVER be placed under `artifacts/`.

### Special Case: reference_fixes/

`reference_fixes/` is **version-controlled ground truth data**. It contains reference implementations used by preflight validation to verify case correctness.

It must be:
- version controlled (committed to git)
- never generated at runtime
- never stored under `artifacts/`
- always present for preflight validation to succeed

Placement: `data/reference_fixes/` — alongside case definitions.

### Data / Logs / Artifacts Distinction

| Directory | Classification | Deletable? | Required for execution? | Writable at runtime? |
|---|---|---|---|---|
| `data/` | Ground truth inputs | NO | YES — cases, reference fixes | **NO — read-only** |
| `logs/` | Runtime traces | YES (per-run) | NO — but produced by execution | YES — write target |
| `artifacts/` | Generated outputs | YES | NO — reports, plans, audits | NO — not used at runtime |

**Hard rule:** If deleting a directory breaks `python run.py`, it is NOT an artifact.

### Data Invariant

The `data/` directory is **READ-ONLY at runtime**.

- No code may write to `data/`
- All runtime outputs must go to `logs/`
- All generated analysis/reports must go to `artifacts/`
- Any mutation of `data/` is a critical error

### Logs Role

`logs/` contains **ephemeral runtime traces**.

- Logs are NOT reproducible inputs — they are per-run output
- Analysis scripts consume structured event data from `logs/` (merged_events.jsonl)
- Logs may be deleted without affecting system correctness (only historical data is lost)

### Root-level files

| File | Action |
|---|---|
| `CLAUDE.md` | Stays. No path changes needed (`rules/` stays at root). |
| `errors.txt` | Move to `artifacts/errors.txt` |
| `snapshot.txt` | Move to `artifacts/snapshot.txt` |
| `analysis_results.md` | Move to `artifacts/analysis_results.md` |

---

## 2. Final Root Directory Tree

```
t3_code_generation/
│
├── core/                    # foundational types, config, registries
├── pipeline/                # generation, parsing, execution, retry
├── evaluation/              # evaluators, reasoning metrics, scoring
├── orchestration/           # runners, CLI, coordination
├── logging_/                # logging + metrics emission
├── analysis/                # offline analysis scripts
├── data/                    # case definitions + ground truth
│   └── reference_fixes/     # ground truth reference implementations (validation data)
│
├── artifacts/               # GENERATED outputs only (safe to delete)
│   ├── plans/               # generated plans only
│   ├── docs/                # generated reports only
│   ├── audits/
│   ├── analysis_output/
│   ├── deep_research_reports/
│   ├── auto_plans/
│   ├── experiments/
│   ├── _archive/
│   │   └── assembly/       # dead package, archived
│   ├── errors.txt
│   ├── snapshot.txt
│   └── analysis_results.md
│
├── rules/                   # LLM behavioral rules (CONTROL PLANE — not an artifact)
├── nudges/                  # runtime prompt operators (imported by condition_registry + execution)
├── logs/                    # runtime execution logs (NOT artifacts)
├── configs/                 # experiment YAML configs
├── prompts/                 # prompt templates (Jinja2)
├── templates/               # template definitions
├── tests/                   # test suites
├── tests_v2/                # v2 test suites
├── scripts/                 # standalone scripts
├── graph_runner/            # graph-based runner
├── harness/                 # test harness
├── validation/              # validation utilities
├── evaluators/              # oracle evaluator (importable)
├── code_snippets/           # v1 case code files
├── code_snippets_v2/        # v2 case code files
│
├── run.py                   # CLI entrypoint
├── CLAUDE.md                # LLM instructions
└── pyrightconfig.json       # IDE config
```

**Root-level directories: 22** (down from 28)
**Root-level files: 3** (down from 70+)

---

## 3. Path Impact Report

| File | Path reference | Old | New |
|---|---|---|---|
| scripts/run_oracle_eval.py:356 | `--output-dir` default | `audits/oracle_eval` | `artifacts/audits/oracle_eval` |
| scripts/run_oracle_intervention.py:231 | `--output-dir` default | `audits/oracle_intervention` | `artifacts/audits/oracle_intervention` |
| preflight_check.py:92 | reference_fixes path | `"reference_fixes"` | `"data/reference_fixes"` |
| scripts/generate_v2_report.py:721 | docs output path | `"docs/v2_ablation_report.md"` | `"artifacts/docs/v2_ablation_report.md"` |

**Total: 4 files need path string updates. Zero import changes. Zero logic changes. CLAUDE.md unchanged.**

---

## 4. Validation Summary

### Pre-move checks
- [x] No Python imports from `plans/`, `docs/`, `analysis_output/`, `deep_research_reports/`, `auto_plans/`, `experiments/`, `_archive/`
- [x] `nudges/` is runtime code (imported by condition_registry + execution) — stays at root
- [x] `rules/` is control plane — stays at root, CLAUDE.md references unchanged
- [x] `audits/` referenced only by 2 scripts as output directory defaults
- [x] `reference_fixes/` is validation ground truth — moves to `data/reference_fixes/`, NOT artifacts
- [x] `evaluators/` is importable Python — DO NOT MOVE

### Post-move validation
- [ ] `python run.py --help` works
- [ ] `python -m pytest tests/ --collect-only` discovers tests
- [ ] `python -c "from evaluators.reasoning_truth import evaluate_reasoning"` works
- [ ] `ls artifacts/plans/` shows moved content
- [ ] `grep -rn "rules/" CLAUDE.md` shows `rules/` paths (unchanged, NOT artifacts/)
- [ ] `rules/` directory exists at project root
- [ ] No broken path references: `grep -rn '"audits/' scripts/*.py | grep -v artifacts` returns 0

---

## 5. Artifact Invariant

All contents of `artifacts/` MUST be:
- **Generated outputs** (reports, analysis results, planning documents)
- **Safe to delete** without breaking any runtime execution
- **Not required** for system operation, validation, or ground truth

**Hard rule:** If `rm -rf artifacts/` breaks any `python run.py` execution, any test, or any validation check, the classification is wrong and the offending directory must be moved out of `artifacts/`.

### Directory classifications

| Directory | Classification | Why artifacts/ is correct |
|---|---|---|
| `plans/` | Generated planning documents | Produced during development sessions. Not consumed by code. |
| `docs/` | Generated reports | Output of analysis scripts (e.g., `generate_v2_report.py`). Not source inputs. |
| `audits/` | Generated audit outputs | Output directories for oracle evaluation scripts. |
| `analysis_output/` | Generated analysis results | Output of analysis runs. |
| `deep_research_reports/` | Generated research output | Research reports, not source code. |
| `auto_plans/` | Auto-generated plans | Machine-generated, not hand-authored source. |
| `experiments/` | Experiment output | Results from experimental runs. |
| `_archive/` | Archived dead code/output | Explicitly deprecated material. |

---

## 6. Path Invariant

All file access in the codebase MUST use `PROJECT_ROOT`-based resolution:

```python
from core.config.paths import PROJECT_ROOT
path = PROJECT_ROOT / "case_data" / "cases_v2.json"
```

**Forbidden:**
- Raw string paths assuming cwd: `open("cases_v2.json")`
- `Path(__file__).parent` for project-level resources (only valid for file-relative resources like sibling templates)

This invariant is enforced during the v3 code reorg (Phase 14) and applies to all path updates in this plan.

The `preflight_check.py` reference_fixes path update MUST use this pattern:
```python
ref_path = PROJECT_ROOT / "case_data" / "reference_fixes" / f"{cid}.py"
```

---

## 7. Strengthened Validation

### Post-move existence checks
```python
from core.config.paths import PROJECT_ROOT
# Artifact directories exist
for d in ["plans", "docs", "audits", "analysis_output", "deep_research_reports",
          "auto_plans", "experiments", "_archive"]:
    assert (PROJECT_ROOT / "artifacts" / d).exists(), f"artifacts/{d} missing"
# Ground truth case_data exists
assert (PROJECT_ROOT / "case_data" / "reference_fixes").exists(), "case_data/reference_fixes missing"
# Control plane exists
assert (PROJECT_ROOT / "CLAUDE_RULES").exists(), "CLAUDE_RULES/ missing from root"
assert (PROJECT_ROOT / "CLAUDE_RULES" / "ENTRYPOINT.md").exists(), "CLAUDE_RULES/ENTRYPOINT.md missing"
# Artifact invariant: system runs WITHOUT artifacts/ present
# Enforced by simulated deletion test (Phase 19)
```

### Preflight validation
```python
from core.config.paths import PROJECT_ROOT
p = PROJECT_ROOT / "case_data" / "reference_fixes"
assert p.exists(), "case_data/reference_fixes/ missing"
assert len(list(p.glob("*.py"))) > 0, "no reference fix files found"
```

### Artifact directory structure enforcement
```python
from core.config.paths import PROJECT_ROOT

EXPECTED_ARTIFACT_DIRS = {
    "plans", "docs", "audits", "analysis_output",
    "deep_research_reports", "auto_plans",
    "experiments", "_archive"
}

actual = {p.name for p in (PROJECT_ROOT / "artifacts").iterdir() if p.is_dir()}
assert actual == EXPECTED_ARTIFACT_DIRS, \
    f"Unexpected artifact dirs: {actual - EXPECTED_ARTIFACT_DIRS}"
```
This prevents silent directory drift — any new directory appearing under `artifacts/` must be explicitly added to the expected set.

### Full validation checklist (updated)
- [ ] `python run.py --help` works
- [ ] `python -m pytest tests/ --collect-only` discovers tests
- [ ] `python -c "from evaluators.reasoning_truth import evaluate_reasoning"` works
- [ ] All 8 artifact directories exist under `artifacts/`
- [ ] `data/reference_fixes/` exists with .py files
- [ ] `rules/` exists at project root
- [ ] `rules/ENTRYPOINT.md` exists
- [ ] `grep -rn "rules/" CLAUDE.md` shows `rules/` paths (unchanged)
- [ ] `grep -rn '"audits/' scripts/*.py | grep -v artifacts` returns 0
- [ ] `grep -rn '"reference_fixes"' *.py scripts/*.py | grep -v data/` returns 0
- [ ] Preflight check resolves reference fixes at new path

---

## Integration with v3

This is an additive phase appended to the v3 execution plan:

### Phase 16: Create artifacts/ directory
```bash
mkdir -p artifacts
```

### Phase 17: Move artifact directories
```bash
## Step 1: Dry run — list what will move
echo "=== Artifact directories to move ==="
for dir in plans docs audits analysis_output deep_research_reports auto_plans experiments _archive; do
  [ -d "$dir" ] && echo "  $dir/ → artifacts/$dir/" || echo "  MISSING: $dir/"
done
echo "  assembly/ → artifacts/_archive/assembly/"
echo "  reference_fixes/ → data/reference_fixes/"
echo ""
echo "=== Artifact files to move ==="
for f in errors.txt snapshot.txt analysis_results.md; do
  [ -f "$f" ] && echo "  $f → artifacts/$f" || echo "  MISSING: $f"
done
echo ""
echo "Review above. Proceed? [y/N]"

## Step 2: Execute moves
for dir in plans docs audits analysis_output deep_research_reports auto_plans experiments _archive; do
  [ -d "$dir" ] && mv "$dir" artifacts/
done
[ -d assembly ] && mv assembly artifacts/_archive/assembly
[ -d reference_fixes ] && mv reference_fixes case_data/reference_fixes
for f in errors.txt snapshot.txt analysis_results.md; do
  [ -f "$f" ] && mv "$f" artifacts/
done

## Step 3: Validate immediately
echo "=== Post-move validation ==="
for dir in plans docs audits analysis_output deep_research_reports auto_plans experiments _archive; do
  [ -d "artifacts/$dir" ] && echo "  OK: artifacts/$dir/" || echo "  FAIL: artifacts/$dir/ missing"
done
[ -d "data/reference_fixes" ] && echo "  OK: data/reference_fixes/" || echo "  FAIL: data/reference_fixes/ missing"
[ -d "rules" ] && echo "  OK: rules/ at root" || echo "  FAIL: rules/ missing from root"
```

### Phase 18: Update path references
- Update scripts/run_oracle_eval.py: update default `--output-dir`
- Update scripts/run_oracle_intervention.py: update default `--output-dir`
- Update preflight_check.py: `reference_fixes` → `data/reference_fixes`
- Update scripts/generate_v2_report.py: `docs/` → `artifacts/docs/`

### Phase 19: VALIDATE

#### Standard checks
- Run all post-move validation checks from Section 7
- Verify `python run.py --help`
- Verify test discovery

#### Artifact deletion test (MANDATORY)
```bash
# Simulate artifact deletion — system MUST still work without artifacts/
# Artifacts are ALWAYS restored, even on failure.
mv artifacts artifacts_tmp
if python run.py --help && python -m pytest tests/ --collect-only; then
    mv artifacts_tmp artifacts
    echo "Artifact invariant: PASSED"
else
    mv artifacts_tmp artifacts
    echo "Artifact invariant: FAILED"
    exit 1
fi
```
If this fails, artifact classification is incorrect. Find the offending directory and move it out of `artifacts/`.

#### Runtime ground truth enforcement
```python
from core.config.paths import PROJECT_ROOT
assert (PROJECT_ROOT / "case_data/reference_fixes").exists(), \
    "FATAL: case_data/reference_fixes/ missing — required ground truth"
```
This assertion must be enforced in preflight_check.py or runner.py startup validation.
