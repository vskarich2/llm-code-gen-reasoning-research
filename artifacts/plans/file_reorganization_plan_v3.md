# File Reorganization Plan — v3

**Supersedes:** file_reorganization_plan_v2.md
**Type:** Structural reorganization (file moves + import updates + minimal symbol extractions)
**Logic changes:** ZERO
**Date:** 2026-04-02

---

## 1. Executive Summary

Reorganize 59 root-level files into 7 packages with strict one-directional dependency flow. This revision fixes v2's hidden coupling (`evaluation` → `pipeline` via deferred imports), polluted `core/` (operational modules misclassified as foundational), and unresolved `exec_eval` boundary.

Key structural decisions:
- `llm.py` stays in `pipeline/`. Evaluation's need for `call_model` is resolved by accepting that `evaluator.py` is an orchestration-boundary module, not a pure evaluation module.
- `code_assembly.py` stays in `pipeline/`. The `AssemblyResult` dataclass is extracted to `core/types.py`.
- `exec_eval.py` moves to `pipeline/execution/` — it is execution infrastructure, not evaluation.
- Pure text extraction functions (`extract_code`, `extract_all_code_blocks`) are extracted from `parse.py` into `core/text_extraction.py`.
- Zero deferred cross-layer imports remain.

---

## 2. Corrections from v2

| v2 Issue | v3 Fix |
|---|---|
| `llm.py` dumped in `core/` | Stays in `pipeline/`. `evaluator.py` reclassified as orchestration-boundary (see Section 7) |
| `code_assembly.py` dumped in `core/` | Stays in `pipeline/`. `AssemblyResult` dataclass extracted to `core/types.py` |
| `eval_cases.py` in `core/` without justification | Moved to `evaluation/` where its only consumer lives |
| Deferred imports used as loophole | Eliminated. All cross-layer deps resolved structurally (see Section 6) |
| `exec_eval.py` in `evaluation/` with parse dependency | Moved to `pipeline/execution/` — it IS execution infrastructure |
| `PROJECT_ROOT` in `core/__init__.py` | Moved to `core/config/paths.py` |
| `evaluator.py` classified as pure evaluation | Reclassified as orchestration-boundary module in `orchestration/` — it coordinates LLM calls, prompt assembly, execution eval, and classification. That is orchestration. |
| `module_exec.py` dependency from evaluator.py | No longer cross-layer — both in their correct packages, wired by orchestration |

---

## 3. Final Directory Structure

```
t3_code_generation/
│
├── core/
│   ├── __init__.py               # empty
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── contract.py
│   │   └── contracts_v2.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   ├── experiment_config.py
│   │   └── paths.py              # PROJECT_ROOT + path resolution
│   ├── registry/
│   │   ├── __init__.py
│   │   ├── condition_registry.py
│   │   └── prompt_registry.py
│   ├── types.py                  # AssemblyResult, ParsedGenerationV2 — shared dataclasses only
│   ├── text_extraction.py        # extract_code, extract_all_code_blocks — pure regex
│   └── _stdlib.py
│
├── pipeline/
│   ├── __init__.py
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── assembly_engine.py
│   │   ├── prompts.py
│   │   └── templates.py
│   ├── parsing/
│   │   ├── __init__.py
│   │   ├── parse.py
│   │   └── parser_v2.py
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── execution.py
│   │   ├── execution_v2.py
│   │   ├── exec_eval.py          # MOVED HERE from evaluation
│   │   ├── exec_canonical.py
│   │   └── module_exec.py
│   ├── retry/
│   │   ├── __init__.py
│   │   ├── retry_harness.py
│   │   └── retry_v2.py
│   ├── llm.py
│   ├── code_assembly.py
│   ├── diff_gate.py
│   ├── leg_reduction.py
│   ├── llm_mock.py
│   └── reconstructor.py
│
├── evaluation/
│   ├── __init__.py
│   ├── evaluator_v2.py
│   ├── reasoning.py
│   ├── reasoning_v2.py
│   ├── mapping_v2.py
│   ├── metrics_v2.py
│   ├── score_execution.py
│   ├── failure_classifier.py
│   ├── disagreement_classifier.py
│   ├── leg_evaluator.py
│   └── eval_cases.py             # tiny text-matching helpers, used by evaluator.py
│
├── orchestration/
│   ├── __init__.py
│   ├── runner.py
│   ├── orchestrate.py
│   ├── parallel_runner.py
│   ├── evaluator.py              # MOVED HERE — it orchestrates LLM + eval + classify
│   ├── preflight_check.py
│   ├── merge_run.py
│   ├── validate_cases_v2.py
│   └── create.py
│
├── logging_/
│   ├── __init__.py
│   ├── logging_core.py
│   ├── call_logger.py
│   ├── redis_metrics.py
│   ├── live_metrics.py
│   ├── v2_metrics.py
│   └── v2_dashboard.py
│
├── analysis/
│   ├── (existing .md files — untouched)
│   ├── load_logs.py
│   ├── run_full_analysis.py
│   ├── run_family_intervention_comparison.py
│   ├── run_mechanism_diagnosis.py
│   ├── run_leg_subtypes.py
│   ├── aggregate.py
│   ├── join_reasoning_execution.py
│   └── scm_data.py
│
├── data/
│   ├── cases.json
│   ├── cases_v2.json
│   ├── cases_v2_ffd.json
│   ├── cases_v2_ffd2.json
│   ├── cases_v2_hard.json
│   ├── cases_v2_leg_hotspots.json
│   ├── cases_v2_mb_eo.json
│   ├── cases_v2_parse_failures.json
│   ├── cases_vskarich_test.json
│   └── ablation_config.yaml
│
├── run.py                        # thin wrapper: from orchestration.runner import main; main()
├── pyrightconfig.json
│
├── configs/         # UNTOUCHED (import paths updated in YAML)
├── prompts/         # UNTOUCHED
├── templates/       # UNTOUCHED
├── tests/           # imports updated
├── tests_v2/        # imports updated
├── scripts/         # imports updated
├── graph_runner/    # UNTOUCHED
├── harness/         # UNTOUCHED
├── validation/      # UNTOUCHED
├── logs/            # UNTOUCHED
├── code_snippets/   # UNTOUCHED
├── code_snippets_v2/# UNTOUCHED
├── evaluators/      # UNTOUCHED
├── assembly/        # UNTOUCHED
├── _archive/        # UNTOUCHED
├── plans/           # UNTOUCHED
├── rules/           # UNTOUCHED
├── docs/            # UNTOUCHED
├── deep_research_reports/ # UNTOUCHED
├── nudges/          # UNTOUCHED
├── reference_fixes/ # UNTOUCHED
├── auto_plans/      # UNTOUCHED
├── audits/          # UNTOUCHED
├── experiments/     # UNTOUCHED
└── analysis_output/ # UNTOUCHED
```

---

## 4. File Move Plan

### → core/contracts/
| Old | New |
|---|---|
| contract.py | core/contracts/contract.py |
| contracts_v2.py | core/contracts/contracts_v2.py |

### → core/config/
| Old | New |
|---|---|
| constants.py | core/config/constants.py |
| experiment_config.py | core/config/experiment_config.py |

### → core/registry/
| Old | New |
|---|---|
| condition_registry.py | core/registry/condition_registry.py |
| prompt_registry.py | core/registry/prompt_registry.py |

### → core/ (top level)
| Old | New |
|---|---|
| _stdlib.py | core/_stdlib.py |

### New files in core/ (extracted, not refactored)
| New File | Source | Contents |
|---|---|---|
| core/types.py | parser_v2.py + code_assembly.py | `ParsedGenerationV2` dataclass (from parser_v2.py) + `AssemblyResult` dataclass (from code_assembly.py). Imports only: `dataclasses`, `typing`. Zero logic. |
| core/text_extraction.py | parse.py | `extract_code()` and `extract_all_code_blocks()` — pure regex functions. Imports only: `re`, `logging`. Zero pipeline dependencies. |
| core/config/paths.py | new | `PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent` |

### → pipeline/
| Old | New |
|---|---|
| llm.py | pipeline/llm.py |
| llm_mock.py | pipeline/llm_mock.py |
| code_assembly.py | pipeline/code_assembly.py |
| diff_gate.py | pipeline/diff_gate.py |
| leg_reduction.py | pipeline/leg_reduction.py |
| reconstructor.py | pipeline/reconstructor.py |

### → pipeline/generation/
| Old | New |
|---|---|
| assembly_engine.py | pipeline/generation/assembly_engine.py |
| prompts.py | pipeline/generation/prompts.py |
| templates.py | pipeline/generation/templates.py |

### → pipeline/parsing/
| Old | New |
|---|---|
| parse.py | pipeline/parsing/parse.py |
| parser_v2.py | pipeline/parsing/parser_v2.py |

### → pipeline/execution/
| Old | New |
|---|---|
| execution.py | pipeline/execution/execution.py |
| execution_v2.py | pipeline/execution/execution_v2.py |
| exec_eval.py | pipeline/execution/exec_eval.py |
| exec_canonical.py | pipeline/execution/exec_canonical.py |
| module_exec.py | pipeline/execution/module_exec.py |

### → pipeline/retry/
| Old | New |
|---|---|
| retry_harness.py | pipeline/retry/retry_harness.py |
| retry_v2.py | pipeline/retry/retry_v2.py |

### → evaluation/
| Old | New |
|---|---|
| evaluator_v2.py | evaluation/evaluator_v2.py |
| reasoning.py | evaluation/reasoning.py |
| reasoning_v2.py | evaluation/reasoning_v2.py |
| mapping_v2.py | evaluation/mapping_v2.py |
| metrics_v2.py | evaluation/metrics_v2.py |
| score_execution.py | evaluation/score_execution.py |
| failure_classifier.py | evaluation/failure_classifier.py |
| disagreement_classifier.py | evaluation/disagreement_classifier.py |
| leg_evaluator.py | evaluation/leg_evaluator.py |
| eval_cases.py | evaluation/eval_cases.py |

### → orchestration/
| Old | New |
|---|---|
| runner.py | orchestration/runner.py |
| orchestrate.py | orchestration/orchestrate.py |
| parallel_runner.py | orchestration/parallel_runner.py |
| evaluator.py | orchestration/evaluator.py |
| preflight_check.py | orchestration/preflight_check.py |
| merge_run.py | orchestration/merge_run.py |
| validate_cases_v2.py | orchestration/validate_cases_v2.py |
| create.py | orchestration/create.py |

### → logging_/
| Old | New |
|---|---|
| logging_core.py | logging_/logging_core.py |
| call_logger.py | logging_/call_logger.py |
| redis_metrics.py | logging_/redis_metrics.py |
| live_metrics.py | logging_/live_metrics.py |
| v2_metrics.py | logging_/v2_metrics.py |
| v2_dashboard.py | logging_/v2_dashboard.py |

### → analysis/
| Old | New |
|---|---|
| load_logs.py | analysis/load_logs.py |
| run_full_analysis.py | analysis/run_full_analysis.py |
| run_family_intervention_comparison.py | analysis/run_family_intervention_comparison.py |
| run_mechanism_diagnosis.py | analysis/run_mechanism_diagnosis.py |
| run_leg_subtypes.py | analysis/run_leg_subtypes.py |
| aggregate.py | analysis/aggregate.py |
| join_reasoning_execution.py | analysis/join_reasoning_execution.py |
| scm_data.py | analysis/scm_data.py |

### → data/
| Old | New |
|---|---|
| cases.json → cases_vskarich_test.json | data/ (all 10 files) |
| ablation_config.yaml | data/ablation_config.yaml |

**Total: 60 files moved, 3 files extracted (types.py, text_extraction.py, paths.py), 1 new (run.py), 15 __init__.py files.**

---

## 5. Layer Dependency Rules

```
core:          ZERO outward dependencies. stdlib + third-party only.
pipeline:      may import core ONLY.
evaluation:    may import core ONLY.
logging_:      may import core ONLY.
orchestration: may import core, pipeline, evaluation, logging_.
analysis:      may import anything.
```

**No exceptions. No deferred imports across these boundaries.**

Enforcement after each phase:
```bash
# Must return 0 results:
grep -rn "from pipeline\|from orchestration\|from logging_\|from analysis\|from evaluation" core/
grep -rn "from pipeline\|from orchestration\|from logging_" evaluation/
grep -rn "from evaluation\|from orchestration\|from logging_" pipeline/
grep -rn "from orchestration" logging_/
```

---

## 6. Deferred Import Policy

### Allowed categories
1. **Optional third-party dependencies** (e.g., `import redis` inside a function when redis may not be installed)
2. **Config access at call time** (e.g., `from core.config.experiment_config import get_config` inside a function body to avoid import-time config requirement). This is intra-layer and does not cross boundaries.

### Forbidden categories
1. **Cross-layer boundary bypasses** — no deferred import from evaluation→pipeline, pipeline→evaluation, core→anything operational
2. **Dependency concealment** — if module A calls module B at runtime, A depends on B and that must be reflected in the layer rules

### Remaining deferred imports (exhaustive list)

| File | Deferred import | Category | Justification |
|---|---|---|---|
| pipeline/llm.py | `from core.config.experiment_config import get_config` (6 sites) | Config access at call time | Avoids requiring config at import time. Intra-allowed dependency (pipeline→core). |
| pipeline/llm.py | `from pipeline.llm_mock import mock_call` | Optional fallback | Only invoked when no API key is set. Same layer. |

**Zero cross-layer deferred imports remain.**

---

## 7. Shared-Layer Boundary Rationale

### core/types.py — 2 extracted dataclasses

**ParsedGenerationV2** (from parser_v2.py): A frozen dataclass with string/list fields. Used by both `pipeline/parsing/parser_v2.py` (produces it) and `evaluation/reasoning_v2.py` (consumes it). Extracting only the dataclass definition (no logic) keeps core minimal while eliminating evaluation→pipeline coupling.

**AssemblyResult** (from code_assembly.py): A frozen dataclass with string fields. Used by `pipeline/code_assembly.py` (produces it) and `pipeline/execution/exec_eval.py` (consumes it). While both are in pipeline, the type definition belongs in core/types.py for consistency — it's a shared data structure, not operational logic.

**Why not keep them in their source files?** ParsedGenerationV2 in parser_v2.py would force evaluation to import from pipeline. AssemblyResult is co-located for consistency and because future evaluation modules may need it.

### core/text_extraction.py — 2 extracted functions

**extract_code()** and **extract_all_code_blocks()** are pure regex functions (import only `re` and `logging`). They currently live in `parse.py` (pipeline) but are needed by `exec_eval.py` (also pipeline after v3, so this extraction is optional). Extracted to core anyway because they are genuinely format-level text utilities with zero pipeline semantics.

**Why not leave them in parse.py?** They are pure text operations, not parsing pipeline logic. Extracting them makes parse.py a thinner pipeline module and makes the text extraction available to any layer without coupling.

### evaluator.py → orchestration/evaluator.py

**Why orchestration, not evaluation?** `evaluator.py` is not a pure evaluator. It:
- Calls `call_model()` (LLM integration — pipeline)
- Calls `assembly_engine.build()` (prompt construction — pipeline)
- Calls `run_module_execution()` (execution — pipeline)
- Calls `classify_disagreement()` (evaluation)
- Calls `exec_evaluate()` (execution — pipeline)

It orchestrates pipeline and evaluation components together. That is orchestration, not evaluation. Placing it in `evaluation/` forced cross-layer imports. Placing it in `orchestration/` makes all its dependencies legal (orchestration may import pipeline + evaluation).

### pipeline/llm_mock.py

Moved to pipeline because it is only imported by pipeline/llm.py. Not foundational.

---

## 8. exec_eval Boundary Resolution

### Responsibility
`exec_eval.py` is **execution infrastructure**: it takes assembled code, runs it in a subprocess against test cases, and returns pass/fail results. It is the ground-truth execution boundary.

### Placement
`pipeline/execution/exec_eval.py` — it belongs with execution logic, not evaluation.

### May import
- `core/*` (contracts, types, text_extraction, config, _stdlib)
- `pipeline/*` (parse utilities, code_assembly) — same layer

### Must NOT import
- `evaluation/*` — exec_eval produces execution truth; evaluation consumes it. One-directional.
- `orchestration/*`
- `logging_/*`

### Parsing-related helpers resolution
`exec_eval.py` imports `extract_code` and `extract_all_code_blocks` from `parse.py`. These two functions are extracted to `core/text_extraction.py` — pure regex, no pipeline dependencies. exec_eval imports from core, not pipeline/parsing.

`exec_eval.py` imports `CodeAssembler` and `AssemblyResult` from `code_assembly.py`. After the move, both are in `pipeline/` — same layer, legal import. `AssemblyResult` dataclass is also in `core/types.py` for the type definition; exec_eval can import from either.

**Net result:** exec_eval depends only on core + pipeline (same layer). Zero evaluation or orchestration dependencies.

---

## 9. Path Resolution Plan

### core/config/paths.py (new file)
```python
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
```

### Files requiring BASE_DIR update (9 files)

| File (new path) | Old pattern | New pattern |
|---|---|---|
| orchestration/runner.py | `BASE_DIR = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE_DIR` |
| core/registry/prompt_registry.py | `BASE_DIR = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE_DIR` |
| pipeline/execution/execution.py | `BASE_DIR = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE_DIR` |
| pipeline/execution/exec_eval.py | `_EXEC_EVAL_DIR = Path(__file__).resolve().parent` | `from core.config.paths import PROJECT_ROOT as _EXEC_EVAL_DIR` |
| pipeline/execution/exec_canonical.py | `PROJECT_ROOT = str(Path(__file__).resolve().parent)` | `from core.config.paths import PROJECT_ROOT` |
| orchestration/preflight_check.py | `BASE = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE` |
| pipeline/retry/retry_harness.py | `BASE_DIR = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE_DIR` |
| orchestration/validate_cases_v2.py | `BASE = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE` |
| pipeline/generation/templates.py | `BASE_DIR = Path(__file__).parent` | `from core.config.paths import PROJECT_ROOT as BASE_DIR` |

### YAML config path updates (Phase 14)

Pattern: `source: "cases_v2.json"` → `source: "data/cases_v2.json"`

```bash
# All config_storage
find config_storage/ -name "*.yaml" -exec sed -i '' 's|source: "cases_|source: "case_data/cases_|g' {} +
find config_storage/ -name "*.yaml" -exec sed -i '' 's|source: cases_|source: case_data/cases_|g' {} +
# Scripts
find scripts/ -name "*.py" -exec sed -i '' 's|"cases_v2|"case_data/cases_v2|g' {} +
find scripts/ -name "*.py" -exec sed -i '' 's|"cases\.|"case_data/cases.|g' {} +
```

Validate: `grep -rn "source:.*cases_" configs/ | grep -v "data/"` must return 0.

---

## 10. Phased Execution Plan

### Phase 1: Create directories + __init__.py
Create all directories and 15 empty __init__.py files.
**Validate:** All directories exist.

### Phase 2: Create core extraction files
- Create `core/config/paths.py` (PROJECT_ROOT)
- Extract `ParsedGenerationV2` from parser_v2.py → `core/types.py`
- Extract `AssemblyResult` from code_assembly.py → `core/types.py`
- Extract `extract_code`, `extract_all_code_blocks` from parse.py → `core/text_extraction.py`
- Update source files to import from new locations
- **Validate:** `python -c "from core.types import ParsedGenerationV2, AssemblyResult; from core.text_extraction import extract_code"`

### Phase 3: Move core/ files
Move: constants.py, contracts_v2.py, contract.py, experiment_config.py, condition_registry.py, prompt_registry.py, _stdlib.py. Update all imports.
**Validate:** `python -c "from core.config.constants import V2_CONDITIONS; from core.registry.prompt_registry import load_prompt_registry"`

### Phase 4: VALIDATE core isolation
```bash
grep -rn "from pipeline\|from orchestration\|from logging_\|from analysis\|from evaluation" core/
```
Must return 0.

### Phase 5: Move evaluation/ files
Move: evaluator_v2.py, reasoning.py, reasoning_v2.py, mapping_v2.py, metrics_v2.py, score_execution.py, failure_classifier.py, disagreement_classifier.py, leg_evaluator.py, eval_cases.py. Update imports.
**Validate:** `python -c "from evaluation.evaluator_v2 import ClassifierResultV2"`

### Phase 6: VALIDATE evaluation isolation
```bash
grep -rn "from pipeline\|from orchestration\|from logging_" evaluation/
```
Must return 0.

### Phase 7: Move pipeline/ files
Move all 15 pipeline files into subdirectories. Update imports.
**Validate:** `python -c "from pipeline.execution.execution_v2 import run_v2; from pipeline.llm import call_model"`

### Phase 8: VALIDATE pipeline isolation
```bash
grep -rn "from evaluation\|from orchestration\|from logging_" pipeline/
```
Must return 0.

### Phase 9: Move logging_/ files
Move all 6 files. Update imports.
**Validate:** `python -c "import logging; from logging_.logging_core import EventLogger"` — both succeed, no shadowing.

### Phase 10: VALIDATE logging_ isolation
```bash
grep -rn "from orchestration\|from pipeline\|from evaluation" logging_/
```
Must return 0.

### Phase 11: Move analysis/ files
Move all 8 files. Update imports.
**Validate:** `python -c "from analysis.load_logs import load_logs"`

### Phase 12: Move orchestration/ files
Move all 8 files (including evaluator.py). Create run.py wrapper. Update imports.
**Validate:** `python -c "from orchestration.runner import main; from orchestration.evaluator import evaluate_case"`

### Phase 13: FULL IMPORT VALIDATION
```bash
for pkg in core pipeline evaluation orchestration logging_ analysis; do
  find $pkg -name "*.py" -exec python -m py_compile {} +
done
```

### Phase 14: Path migration
- Move all data/ files
- Run sed commands for YAML configs (125 files) and scripts (26 files)
- Update hardcoded case paths in runner.py, load_logs.py, etc.
- **Validate:** `grep -rn "source:.*cases_" configs/ | grep -v "data/"` returns 0

### Phase 15: FINAL SYSTEM CHECK
- `python run.py --help`
- `python -m pytest tests/ --collect-only`
- `python -c "from analysis.load_logs import load_logs; df = load_logs(['logs/v2_targeted_50trial_tranche4']); print(len(df))"`
- Run 1-case smoke test end-to-end

---

## 11. Validation Checklist

- [ ] All `python -m py_compile` passes for every .py file in core/, pipeline/, evaluation/, orchestration/, logging_/, analysis/
- [ ] Layer isolation greps all return 0 (Phases 4, 6, 8, 10)
- [ ] `python run.py --help` works
- [ ] `python -m pytest tests/ --collect-only` discovers tests
- [ ] `python -m pytest tests_v2/ --collect-only` discovers tests
- [ ] `import logging` (stdlib) still works alongside `logging_` package
- [ ] `Path('data/cases_v2.json').exists()` after data move
- [ ] 1-case smoke test passes end-to-end
- [ ] No `from pipeline` in evaluation/ (including function bodies)
- [ ] No `from evaluation` in pipeline/ (including function bodies)
- [ ] Zero deferred cross-layer imports

---

## 12. Risk Register

| Risk | Likelihood | Impact | Detection | Mitigation |
|---|---|---|---|---|
| `evaluator.py` move to orchestration/ breaks imports from execution_v2.py or retry_v2.py | High | High | Phase 7-8 validation | Update all `from evaluator import` → `from orchestration.evaluator import` in pipeline files |
| `extract_code` extraction breaks parse.py internal callers | Medium | Medium | Phase 2 validation | parse.py imports from core/text_extraction.py after extraction |
| YAML sed misses edge cases (quoted vs unquoted, multiline) | Medium | High | Phase 14 grep validation | Manual review of remaining hits after sed |
| scripts/ imports break silently | High | Low | Phase 15: `python -m py_compile scripts/*.py` | Update scripts/ imports |
| `assembly_engine.build` import in orchestration/evaluator.py | None | None | Layer rules allow orchestration→pipeline | Legal dependency |
| prompt_registry BASE_DIR for template loading | Medium | High | Smoke test | BASE_DIR updated to PROJECT_ROOT via paths.py |

---

## 13. Open Decisions

### 1. evaluator.py in orchestration/ — naming concern
`orchestration/evaluator.py` may be confusing alongside `evaluation/evaluator_v2.py`. Options:
- (a) Keep as-is — different packages make the distinction clear
- (b) Rename to `orchestration/case_evaluator.py` — but this violates "no renaming" rule
- **Recommendation:** Keep (a). The module boundary IS the distinction.

### 2. leg_evaluator.py placement
`leg_evaluator.py` imports `call_model` (pipeline) and `assembly_engine.build` (pipeline). It is structurally similar to `evaluator.py` — an orchestration-boundary module. However, it is less central and less frequently called.
- **Current placement:** `evaluation/leg_evaluator.py`
- **Issue:** It imports from pipeline (llm, assembly_engine) — violates evaluation isolation.
- **Options:**
  - (a) Move to `orchestration/leg_evaluator.py` — consistent with evaluator.py treatment
  - (b) Refactor to receive call_model as a callable parameter — but that's a logic change
- **Recommendation:** (a) Move to orchestration. Same rationale as evaluator.py.
- **Impact:** Update Section 3-4 if approved. evaluation/ isolation grep will pass clean.

### 3. score_execution.py placement
Imports `evaluator_v2` only — stays in evaluation, legal.
**Decision:** Keep in evaluation/. No issue.
