# File Reorganization Plan — v1

**Type:** Structural reorganization (file moves + import updates only)
**Scope:** 67 root-level .py files → organized into 7 subdirectories
**Logic changes:** ZERO
**Date:** 2026-04-02

---

## Current State

67 .py files in the project root. No circular dependencies (strict DAG). Three files have 9-10 imports each (runner.py, execution_v2.py, retry_v2.py) — these are the highest-risk files for import breakage.

---

## Target Structure

```
t3_code_generation/
├── core/                    # foundational data structures, contracts, config
│   ├── __init__.py
│   ├── constants.py
│   ├── contracts_v2.py
│   ├── contract.py
│   ├── experiment_config.py
│   ├── condition_registry.py
│   ├── _stdlib.py
│   └── llm_mock.py
│
├── pipeline/                # execution pipeline: generation, parsing, retry
│   ├── __init__.py
│   ├── llm.py
│   ├── parse.py
│   ├── parser_v2.py
│   ├── prompts.py
│   ├── prompt_registry.py
│   ├── assembly_engine.py
│   ├── code_assembly.py
│   ├── reconstructor.py
│   ├── execution.py
│   ├── execution_v2.py
│   ├── retry_harness.py
│   ├── retry_v2.py
│   ├── diff_gate.py
│   ├── leg_reduction.py
│   └── module_exec.py
│
├── evaluation/              # evaluators, classifiers, reasoning, scoring
│   ├── __init__.py
│   ├── evaluator.py
│   ├── evaluator_v2.py
│   ├── reasoning.py
│   ├── reasoning_v2.py
│   ├── mapping_v2.py
│   ├── metrics_v2.py
│   ├── score_execution.py
│   ├── failure_classifier.py
│   ├── disagreement_classifier.py
│   ├── leg_evaluator.py
│   ├── exec_eval.py
│   └── exec_canonical.py
│
├── orchestration/           # top-level runners, orchestration, preflight
│   ├── __init__.py
│   ├── runner.py
│   ├── orchestrate.py
│   ├── parallel_runner.py
│   ├── preflight_check.py
│   ├── merge_run.py
│   └── validate_cases_v2.py
│
├── logging_/                # logging + metrics emission (trailing _ avoids stdlib clash)
│   ├── __init__.py
│   ├── logging_core.py
│   ├── call_logger.py
│   ├── redis_metrics.py
│   ├── live_metrics.py
│   ├── v2_metrics.py
│   └── v2_dashboard.py
│
├── analysis/                # analysis scripts (already exists, add new ones)
│   ├── (existing .md files stay)
│   ├── load_logs.py
│   ├── run_full_analysis.py
│   ├── run_family_intervention_comparison.py
│   ├── run_mechanism_diagnosis.py
│   ├── run_leg_subtypes.py
│   ├── aggregate.py
│   ├── join_reasoning_execution.py
│   └── scm_data.py
│
├── data/                    # case definitions
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
├── configs/                 # (already exists, no changes)
├── prompts/                 # (already exists, no changes)
├── templates/               # (already exists, no changes — has Jinja2 templates)
├── tests/                   # (already exists, no changes)
├── tests_v2/                # (already exists, no changes)
├── scripts/                 # (already exists, no changes)
├── graph_runner/            # (already exists, no changes)
├── harness/                 # (already exists, no changes)
├── validation/              # (already exists, no changes)
├── logs/                    # (already exists, no changes)
├── code_snippets/           # (already exists, no changes)
├── code_snippets_v2/        # (already exists, no changes)
├── plans/                   # (already exists, no changes)
├── rules/                   # (already exists, no changes)
│
├── create.py                # STAYS — standalone case creation utility
├── eval_cases.py            # STAYS — standalone eval script
├── templates.py             # STAYS — standalone template utility
├── pyrightconfig.json       # STAYS — IDE config
└── analysis_results.md      # STAYS — generated output
```

---

## File Move Plan (complete listing)

### → core/
| Old Path | New Path |
|---|---|
| constants.py | core/constants.py |
| contracts_v2.py | core/contracts_v2.py |
| contract.py | core/contract.py |
| experiment_config.py | core/experiment_config.py |
| condition_registry.py | core/condition_registry.py |
| _stdlib.py | core/_stdlib.py |
| llm_mock.py | core/llm_mock.py |

### → pipeline/
| Old Path | New Path |
|---|---|
| llm.py | pipeline/llm.py |
| parse.py | pipeline/parse.py |
| parser_v2.py | pipeline/parser_v2.py |
| prompts.py | pipeline/prompts.py |
| prompt_registry.py | pipeline/prompt_registry.py |
| assembly_engine.py | pipeline/assembly_engine.py |
| code_assembly.py | pipeline/code_assembly.py |
| reconstructor.py | pipeline/reconstructor.py |
| execution.py | pipeline/execution.py |
| execution_v2.py | pipeline/execution_v2.py |
| retry_harness.py | pipeline/retry_harness.py |
| retry_v2.py | pipeline/retry_v2.py |
| diff_gate.py | pipeline/diff_gate.py |
| leg_reduction.py | pipeline/leg_reduction.py |
| module_exec.py | pipeline/module_exec.py |

### → evaluation/
| Old Path | New Path |
|---|---|
| evaluator.py | evaluation/evaluator.py |
| evaluator_v2.py | evaluation/evaluator_v2.py |
| reasoning.py | evaluation/reasoning.py |
| reasoning_v2.py | evaluation/reasoning_v2.py |
| mapping_v2.py | evaluation/mapping_v2.py |
| metrics_v2.py | evaluation/metrics_v2.py |
| score_execution.py | evaluation/score_execution.py |
| failure_classifier.py | evaluation/failure_classifier.py |
| disagreement_classifier.py | evaluation/disagreement_classifier.py |
| leg_evaluator.py | evaluation/leg_evaluator.py |
| exec_eval.py | evaluation/exec_eval.py |
| exec_canonical.py | evaluation/exec_canonical.py |

### → orchestration/
| Old Path | New Path |
|---|---|
| runner.py | orchestration/runner.py |
| orchestrate.py | orchestration/orchestrate.py |
| parallel_runner.py | orchestration/parallel_runner.py |
| preflight_check.py | orchestration/preflight_check.py |
| merge_run.py | orchestration/merge_run.py |
| validate_cases_v2.py | orchestration/validate_cases_v2.py |

### → logging_/
| Old Path | New Path |
|---|---|
| logging_core.py | logging_/logging_core.py |
| call_logger.py | logging_/call_logger.py |
| redis_metrics.py | logging_/redis_metrics.py |
| live_metrics.py | logging_/live_metrics.py |
| v2_metrics.py | logging_/v2_metrics.py |
| v2_dashboard.py | logging_/v2_dashboard.py |

### → analysis/
| Old Path | New Path |
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
| Old Path | New Path |
|---|---|
| cases.json | data/cases.json |
| cases_v2.json | data/cases_v2.json |
| cases_v2_ffd.json | data/cases_v2_ffd.json |
| cases_v2_ffd2.json | data/cases_v2_ffd2.json |
| cases_v2_hard.json | data/cases_v2_hard.json |
| cases_v2_leg_hotspots.json | data/cases_v2_leg_hotspots.json |
| cases_v2_mb_eo.json | data/cases_v2_mb_eo.json |
| cases_v2_parse_failures.json | data/cases_v2_parse_failures.json |
| cases_vskarich_test.json | data/cases_vskarich_test.json |
| ablation_config.yaml | data/ablation_config.yaml |

### Files that STAY in root
| File | Reason |
|---|---|
| create.py | Standalone utility, no imports from/to pipeline |
| eval_cases.py | Standalone utility |
| templates.py | Standalone utility |
| pyrightconfig.json | IDE config |
| analysis_results.md | Generated output |

**Total: 58 files moved, 5 stay.**

---

## Import Changes Required

### Highest-impact files (most imports to update)

**runner.py → orchestration/runner.py** (10 imports to rewrite)

```python
# OLD                              # NEW
from constants import

...          → from core.constants import

...
from condition_registry import

... → from core.condition_registry import

...
from experiment_config import

...  → from core.experiment_config import

...
from prompt_registry import

...    → from core.pipeline import

...
from assembly_engine import

...    → from core.pipeline import

...
from execution_v2 import

...       → from core.pipeline import

...
from retry_v2 import

...           → from core.pipeline import

...
from orchestrate import

...        → from core.pipeline.orchestration import

...
from logging_core import

...       → from core.logging_.logging_core import

...
from code_assembly import

...      → from core.pipeline import

...
```

**execution_v2.py → pipeline/execution_v2.py** (9 imports to rewrite)

```python
from contracts_v2 import

...       → from core.contracts_v2 import

...
from parser_v2 import

...          → from core.pipeline import

...
from reasoning_v2 import

...       → from core.evaluation.reasoning_v2 import

...
from evaluator_v2 import

...       → from core.evaluation.evaluator_v2 import

...
from metrics_v2 import

...         → from core.evaluation import

...
from assembly_engine import

...    → from core.pipeline import

...
from prompts import

...            → from core.pipeline import

...
from llm import

...                → from core.pipeline import

...
from experiment_config import

...  → from core.experiment_config import

...
from execution import

...          → from core.pipeline.execution import

...
```

**retry_v2.py → pipeline/retry_v2.py** (10 imports to rewrite)

```python
from assembly_engine import

...    → from core.pipeline import

...
from evaluator_v2 import

...       → from core.evaluation.evaluator_v2 import

...
from exec_eval import

...          → from core.evaluation import

...
from experiment_config import

...  → from core.experiment_config import

...
from llm import

...                → from core.pipeline import

...
from metrics_v2 import

...         → from core.evaluation import

...
from parser_v2 import

...          → from core.pipeline import

...
from prompts import

...            → from core.pipeline import

...
from reasoning_v2 import

...       → from core.evaluation.reasoning_v2 import

...
from reconstructor import

...      → from core.pipeline.reconstructor import

...
```

### All other import rewrites

| File (new path) | Import change |
|---|---|
| pipeline/llm.py | `experiment_config` → `core.experiment_config`, `llm_mock` → `core.llm_mock` |
| pipeline/parse.py | `reasoning` → `evaluation.reasoning` |
| pipeline/parser_v2.py | `contracts_v2` → `core.contracts_v2` |
| pipeline/assembly_engine.py | `prompt_registry` → `pipeline.prompt_registry` |
| pipeline/code_assembly.py | `_stdlib` → `core._stdlib` |
| pipeline/execution.py | `evaluator` → `evaluation.evaluator`, `llm` → `pipeline.llm`, `parse` → `pipeline.parse` |
| pipeline/retry_harness.py | `llm` → `pipeline.llm`, `parse` → `pipeline.parse`, `evaluator` → `evaluation.evaluator`, `prompts` → `pipeline.prompts` |
| pipeline/leg_reduction.py | `parse` → `pipeline.parse` |
| evaluation/evaluator.py | `exec_eval` → `evaluation.exec_eval`, `llm` → `pipeline.llm`, `reasoning` → `evaluation.reasoning` |
| evaluation/evaluator_v2.py | `contracts_v2` → `core.contracts_v2` |
| evaluation/reasoning_v2.py | `contracts_v2` → `core.contracts_v2`, `mapping_v2` → `evaluation.mapping_v2`, `parser_v2` → `pipeline.parser_v2` |
| evaluation/metrics_v2.py | `contracts_v2` → `core.contracts_v2` |
| evaluation/score_execution.py | `evaluator_v2` → `evaluation.evaluator_v2` |
| evaluation/leg_evaluator.py | `llm` → `pipeline.llm`, `failure_classifier` → `evaluation.failure_classifier`, `assembly_engine` → `pipeline.assembly_engine` |
| evaluation/exec_eval.py | `parse` → `pipeline.parse`, `code_assembly` → `pipeline.code_assembly` |
| orchestration/preflight_check.py | `exec_eval` → `evaluation.exec_eval`, `code_assembly` → `pipeline.code_assembly` |
| orchestration/validate_cases_v2.py | `code_assembly` → `pipeline.code_assembly` |
| logging_/logging_core.py | (verify: may import call_logger → `logging_.call_logger`) |
| analysis/aggregate.py | `logging_core` → `logging_.logging_core` |
| analysis/join_reasoning_execution.py | `metrics_v2` → `evaluation.metrics_v2` |
| analysis/load_logs.py | (no root-level imports — but hardcoded `cases_v2.json` path needs update to `data/cases_v2.json`) |
| analysis/run_*.py | `load_logs` → `analysis.load_logs` |

### Non-Python path references to update

These files reference `cases_v2.json` by path — must update to `data/cases_v2.json`:
- `load_logs.py` (default parameter `cases_path="cases_v2.json"`)
- YAML configs in `configs/` that have `source: "cases_v2.json"`
- `runner.py` (if it resolves case file paths)
- `validate_cases_v2.py`
- `preflight_check.py`

### CLI entrypoint

Currently: `.venv/bin/python runner.py --config ...`
After: `.venv/bin/python -m orchestration.runner --config ...`
OR: add a thin `run.py` wrapper in root that imports `orchestration.runner.main`.

---

## Dependency Direction Validation

Allowed directions (verified):
- orchestration → pipeline ✓
- orchestration → core ✓
- orchestration → evaluation ✓
- orchestration → logging_ ✓
- pipeline → core ✓
- pipeline → evaluation ✓ (execution_v2 imports evaluator_v2, reasoning_v2)
- evaluation → core ✓
- evaluation → pipeline ✓ (evaluator imports llm, exec_eval imports parse)
- analysis → everything ✓
- logging_ → core ✓ (logging_core may import experiment_config)

**Cross-dependency: pipeline ↔ evaluation** — both import from each other. This is existing behavior (not introduced by the reorg). Examples:
- pipeline/execution_v2.py → evaluation/evaluator_v2.py
- evaluation/evaluator.py → pipeline/llm.py
- evaluation/exec_eval.py → pipeline/parse.py

This is NOT a circular import because no individual file pair is circular. The DAG is intact.

---

## Risks

1. **YAML config `source: "cases_v2.json"`** — every config file that references case files needs path update. There are ~50 config files.
2. **Hardcoded paths in scripts/** — scripts that import root-level modules will break. These are in `scripts/` which is "leave as-is" but they import pipeline modules.
3. **`sys.path` manipulation** — some files may add project root to sys.path. Need to verify.
4. **`__main__` blocks** — files like `runner.py` that run as `python runner.py` need either a root wrapper or `-m` invocation.
5. **Template paths** — Jinja2 templates in `prompts/` are loaded by path from assembly_engine.py. These paths must still resolve after assembly_engine moves.

---

## Execution Order

1. Create directories + `__init__.py` files
2. Move `core/` files first (leaf dependencies, no downstream)
3. Move `evaluation/` files (depends only on core)
4. Move `pipeline/` files (depends on core + evaluation)
5. Move `logging_/` files
6. Move `analysis/` files
7. Move `orchestration/` files last (depends on everything)
8. Move `data/` files + update all path references
9. Update all imports in moved files
10. Update all imports in files that reference moved files (scripts/, tests/, etc.)
11. Validate all imports resolve
