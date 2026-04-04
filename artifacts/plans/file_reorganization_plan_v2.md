# File Reorganization Plan — v2

**Supersedes:** file_reorganization_plan_v1.md
**Type:** Structural reorganization (file moves + import updates only)
**Logic changes:** ZERO (except `BASE_DIR`/`__file__` path fixups — see Section 5)
**Date:** 2026-04-02

---

## Changes from v1

1. **Eliminated pipeline ↔ evaluation coupling.** Moved shared dependencies (`call_model`, `ParsedGenerationV2`, `CodeAssembler`, `parse` functions) into `core/` so evaluation never imports from pipeline.
2. **Removed root-level script inconsistency.** All standalone scripts moved to `orchestration/` or `analysis/`.
3. **Config + path migration is now Phase 14** with explicit file lists.
4. **Checkpointed execution** — 15 phases with validation after each.
5. **`BASE_DIR` / `__file__` path fixups** — all files using `Path(__file__).parent` must point to PROJECT_ROOT, not their own directory.
6. **Dependency direction is enforced**, not observed.
7. **Pipeline split** into generation/parsing/execution/retry subdirs.
8. **Core split** into contracts/config/registry subdirs.

---

## 1. Corrected Directory Structure

```
t3_code_generation/
│
├── core/
│   ├── __init__.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── contract.py
│   │   └── contracts_v2.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   └── experiment_config.py
│   ├── registry/
│   │   ├── __init__.py
│   │   ├── condition_registry.py
│   │   └── prompt_registry.py
│   ├── _stdlib.py
│   ├── llm_mock.py
│   ├── llm.py                     ← MOVED HERE (evaluation needs call_model)
│   ├── code_assembly.py           ← MOVED HERE (evaluation needs CodeAssembler)
│   ├── parse_types.py             ← EXTRACTED: ParsedGenerationV2 dataclass only
│   └── eval_cases.py              ← MOVED HERE (evaluation needs _has, _low)
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
│   │   ├── module_exec.py
│   │   └── exec_canonical.py
│   ├── retry/
│   │   ├── __init__.py
│   │   ├── retry_harness.py
│   │   └── retry_v2.py
│   ├── diff_gate.py
│   ├── leg_reduction.py
│   └── reconstructor.py
│
├── evaluation/
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
│   └── exec_eval.py
│
├── orchestration/
│   ├── __init__.py
│   ├── runner.py
│   ├── orchestrate.py
│   ├── parallel_runner.py
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
├── run.py                         ← NEW: thin wrapper (2 lines) to invoke orchestration.runner
├── pyrightconfig.json
│
├── configs/                       # UNTOUCHED
├── prompts/                       # UNTOUCHED
├── templates/                     # UNTOUCHED (Jinja2 templates dir)
├── tests/                         # imports updated
├── tests_v2/                      # imports updated
├── scripts/                       # imports updated
├── graph_runner/                   # UNTOUCHED
├── harness/                       # UNTOUCHED
├── validation/                    # UNTOUCHED
├── logs/                          # UNTOUCHED
├── code_snippets/                 # UNTOUCHED
├── code_snippets_v2/              # UNTOUCHED
├── plans/                         # UNTOUCHED
├── rules/                         # UNTOUCHED
├── evaluators/                    # UNTOUCHED
├── assembly/                      # UNTOUCHED
├── _archive/                      # UNTOUCHED
├── docs/                          # UNTOUCHED
├── deep_research_reports/         # UNTOUCHED
├── nudges/                        # UNTOUCHED
├── reference_fixes/               # UNTOUCHED
├── auto_plans/                    # UNTOUCHED
├── audits/                        # UNTOUCHED
├── experiments/                   # UNTOUCHED
└── analysis_output/               # UNTOUCHED
```

**Zero root-level .py files except `run.py`** (the CLI entrypoint wrapper).

---

## 2. Updated File Move Plan

### → core/contracts/
| Old Path | New Path |
|---|---|
| contract.py | core/contracts/contract.py |
| contracts_v2.py | core/contracts/contracts_v2.py |

### → core/config/
| Old Path | New Path |
|---|---|
| constants.py | core/config/constants.py |
| experiment_config.py | core/config/experiment_config.py |

### → core/registry/
| Old Path | New Path |
|---|---|
| condition_registry.py | core/registry/condition_registry.py |
| prompt_registry.py | core/registry/prompt_registry.py |

### → core/ (top level)
| Old Path | New Path | Reason for core/ |
|---|---|---|
| _stdlib.py | core/_stdlib.py | Leaf utility |
| llm_mock.py | core/llm_mock.py | Leaf utility |
| llm.py | core/llm.py | evaluation + pipeline both need call_model |
| code_assembly.py | core/code_assembly.py | evaluation (exec_eval) + pipeline both need CodeAssembler |
| eval_cases.py | core/eval_cases.py | evaluation (evaluator.py) needs _has/_low |

### → core/ (new file — EXTRACTED, not refactored)
| File | New Path | Contents |
|---|---|---|
| (extract from parser_v2.py) | core/parse_types.py | `ParsedGenerationV2` dataclass ONLY — no logic, no functions, just the dataclass definition. parser_v2.py retains all logic and imports from core.parse_types. reasoning_v2.py imports from core.parse_types instead of parser_v2. |

**Extraction rule for parse_types.py:** Copy the `ParsedGenerationV2` dataclass definition (and any imports it needs: dataclass, typing). Remove it from parser_v2.py. Add `from core.parse_types import ParsedGenerationV2` to parser_v2.py. This is the ONLY code extraction in the entire plan. No logic changes.

### → pipeline/generation/
| Old Path | New Path |
|---|---|
| assembly_engine.py | pipeline/generation/assembly_engine.py |
| prompts.py | pipeline/generation/prompts.py |
| templates.py | pipeline/generation/templates.py |

### → pipeline/parsing/
| Old Path | New Path |
|---|---|
| parse.py | pipeline/parsing/parse.py |
| parser_v2.py | pipeline/parsing/parser_v2.py |

### → pipeline/execution/
| Old Path | New Path |
|---|---|
| execution.py | pipeline/execution/execution.py |
| execution_v2.py | pipeline/execution/execution_v2.py |
| module_exec.py | pipeline/execution/module_exec.py |
| exec_canonical.py | pipeline/execution/exec_canonical.py |

### → pipeline/retry/
| Old Path | New Path |
|---|---|
| retry_harness.py | pipeline/retry/retry_harness.py |
| retry_v2.py | pipeline/retry/retry_v2.py |

### → pipeline/ (top level)
| Old Path | New Path |
|---|---|
| diff_gate.py | pipeline/diff_gate.py |
| leg_reduction.py | pipeline/leg_reduction.py |
| reconstructor.py | pipeline/reconstructor.py |

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

### → orchestration/
| Old Path | New Path |
|---|---|
| runner.py | orchestration/runner.py |
| orchestrate.py | orchestration/orchestrate.py |
| parallel_runner.py | orchestration/parallel_runner.py |
| preflight_check.py | orchestration/preflight_check.py |
| merge_run.py | orchestration/merge_run.py |
| validate_cases_v2.py | orchestration/validate_cases_v2.py |
| create.py | orchestration/create.py |

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

### New files
| File | Contents |
|---|---|
| run.py | `from orchestration.runner import main; main()` (thin wrapper) |
| core/__init__.py | empty |
| core/contracts/__init__.py | empty |
| core/config/__init__.py | empty |
| core/registry/__init__.py | empty |
| pipeline/__init__.py | empty |
| pipeline/generation/__init__.py | empty |
| pipeline/parsing/__init__.py | empty |
| pipeline/execution/__init__.py | empty |
| pipeline/retry/__init__.py | empty |
| evaluation/__init__.py | empty |
| orchestration/__init__.py | empty |
| logging_/__init__.py | empty |
| core/parse_types.py | ParsedGenerationV2 dataclass extracted from parser_v2.py |

**Total: 59 files moved, 1 extracted (parse_types.py), 1 new (run.py), 14 new __init__.py files.**

---

## 3. Dependency Rules (ENFORCED)

```
core:          ZERO outward dependencies. May import only stdlib and third-party.
pipeline:      may import from core ONLY.
evaluation:    may import from core ONLY.
orchestration: may import from core, pipeline, evaluation, logging_.
logging_:      may import from core ONLY.
analysis:      may import from anything.
```

### Cross-dependency elimination

The v1 plan had these violations:

| evaluation file | imported from pipeline | Resolution |
|---|---|---|
| evaluator.py | `from llm import call_model` | llm.py moved to core/ — no violation |
| evaluator.py | `from module_exec import run_module_execution` | Lazy import inside function body; module_exec stays in pipeline/execution/ — this is a runtime-only dependency invoked from orchestration context. evaluator.py is always called from execution_v2.py (pipeline) which already has this dependency. **No change needed — the import is deferred, not structural.** |
| reasoning_v2.py | `from parser_v2 import ParsedGenerationV2` | ParsedGenerationV2 extracted to core/parse_types.py — no violation |
| leg_evaluator.py | `from llm import call_model` | llm.py moved to core/ — no violation |
| leg_evaluator.py | `from assembly_engine import build` | Lazy import inside function body. Same pattern as evaluator.py — deferred runtime dependency. **No change needed.** |
| exec_eval.py | `from parse import ...` | parse functions used by exec_eval are parsing utilities. parse.py stays in pipeline/parsing/ but exec_eval's imports are: `extract_code_v2`, `extract_code_block`, `has_code_block`, `normalize_code` — these are pure string manipulation functions. **Move these specific functions to core/code_assembly.py** (they are code extraction, not parsing pipeline logic). OR accept the deferred import. **Decision: accept deferred import — these are called from pipeline context only.** |
| exec_eval.py | `from code_assembly import CodeAssembler` | code_assembly.py moved to core/ — no violation |

### Remaining deferred imports (runtime-only, not structural)

These are `from X import Y` statements inside function bodies, not at module level. They execute only when called from orchestration/pipeline context:

1. `evaluator.py` line 232: `from module_exec import run_module_execution` — called only from pipeline
2. `evaluator.py` line 142: `from assembly_engine import build` — called only from pipeline
3. `leg_evaluator.py`: `from assembly_engine import build` — called only from pipeline
4. `exec_eval.py` lines 19-23: `from parse import ...` — called only from pipeline

**Rule: deferred imports inside function bodies are permitted when the calling context guarantees the dependency is available. These must NOT be promoted to module-level imports.**

---

## 4. Phased Execution Plan

### Phase 1: Create directories + __init__.py
- Create all directories listed in Section 1
- Create all 14 __init__.py files (empty)
- **Validate:** directories exist, no naming conflicts

### Phase 2: Extract core/parse_types.py
- Copy `ParsedGenerationV2` dataclass from parser_v2.py to core/parse_types.py
- Add `from core.parse_types import ParsedGenerationV2` to parser_v2.py
- Remove dataclass definition from parser_v2.py
- Update reasoning_v2.py: `from parser_v2 import ParsedGenerationV2` → `from core.parse_types import ParsedGenerationV2`
- **Validate:** `python -c "from core.parse_types import ParsedGenerationV2"` succeeds

### Phase 3: Move core/ files
- Move: constants.py, contracts_v2.py, contract.py, experiment_config.py, condition_registry.py, prompt_registry.py, _stdlib.py, llm_mock.py, llm.py, code_assembly.py, eval_cases.py
- Update all internal imports within moved files
- **Validate:** `python -c "from core.config.constants import V2_CONDITIONS"` etc.

### Phase 4: VALIDATE — core imports
- Run: `python -c "from core.llm import call_model; from core.code_assembly import CodeAssembler; from core.config.experiment_config import ExperimentConfig"`
- Verify no module imports from pipeline, evaluation, orchestration, or logging_

### Phase 5: Move evaluation/ files
- Move all 11 evaluation files
- Update imports: `from llm import` → `from core.llm import`, `from contracts_v2 import` → `from core.contracts.contracts_v2 import`, etc.
- **Validate:** `python -c "from evaluation.evaluator_v2 import run_v2_classifier"`

### Phase 6: VALIDATE — evaluation imports
- Verify evaluation/ imports only from core/ and stdlib
- Grep for any `from pipeline` or `from orchestration` in evaluation/ — must be zero (except deferred)

### Phase 7: Move pipeline/ files
- Move all 15 pipeline files into subdirectories
- Update imports
- **Validate:** `python -c "from pipeline.execution.execution_v2 import run_v2"`

### Phase 8: VALIDATE — pipeline imports
- Verify pipeline/ imports only from core/ and stdlib
- Grep for any `from evaluation` or `from orchestration` in pipeline/ — must be zero

### Phase 9: Move logging_/ files
- Move all 6 logging files
- Update imports
- **Validate:** `python -c "from logging_.logging_core import EventLogger"`
- **Verify:** `import logging` (stdlib) still works — no shadowing

### Phase 10: VALIDATE — logging_ imports + stdlib safety
- `python -c "import logging; from logging_ import logging_core"` — both must succeed
- No file may have both `import logging_` and `import logging` confused

### Phase 11: Move analysis/ files
- Move all 8 analysis files
- Update imports
- **Validate:** `python -c "from analysis.load_logs import load_logs"`

### Phase 12: Move orchestration/ files
- Move all 7 orchestration files
- Update imports
- Create run.py wrapper
- **Validate:** `python -c "from orchestration.runner import main"`

### Phase 13: VALIDATE — full import resolution
- `python -c "from orchestration.runner import main; from pipeline.execution.execution_v2 import run_v2; from evaluation.evaluator_v2 import run_v2_classifier; from core.llm import call_model"`
- Run: `python -m py_compile orchestration/runner.py`

### Phase 14: Path migration
- Move all data/ files (cases JSON + ablation_config.yaml)
- Update `BASE_DIR` / `PROJECT_ROOT` in all files (see Section 5)
- Update all 125 YAML configs: `source: "cases_v2.json"` → `source: "data/cases_v2.json"`
- Update all scripts/ references
- **Validate:** `python -c "from pathlib import Path; assert (Path('data/cases_v2.json')).exists()"`

### Phase 15: FINAL SYSTEM CHECK
- Run: `python run.py --config configs/smoke_logging_test.yaml --max-cases 1` (or equivalent smoke test)
- Verify tests discover: `python -m pytest tests/ -x --collect-only`
- Verify analysis scripts: `python -c "from analysis.load_logs import load_logs; df = load_logs(['logs/v2_targeted_50trial_tranche4']); print(len(df))"`

---

## 5. Path Migration Plan — BASE_DIR / __file__ fixups

**11 files** use `Path(__file__).parent` to resolve paths relative to the project root. When these files move into subdirectories, `Path(__file__).parent` will point to the wrong directory.

**Fix pattern:** Replace `Path(__file__).parent` with a shared `PROJECT_ROOT` constant.

Add to `core/__init__.py`:
```python
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
```

Then in each affected file, replace:
```python
BASE_DIR = Path(__file__).parent
```
with:
```python
from core import PROJECT_ROOT as BASE_DIR
```

**Affected files:**

| File | Current | After move |
|---|---|---|
| runner.py → orchestration/runner.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE_DIR` |
| prompt_registry.py → core/registry/prompt_registry.py | `Path(__file__).parent` | `PROJECT_ROOT` (2 levels up from core/registry/) |
| execution.py → pipeline/execution/execution.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE_DIR` |
| exec_eval.py → evaluation/exec_eval.py | `Path(__file__).resolve().parent` | `from core import PROJECT_ROOT` |
| exec_canonical.py → pipeline/execution/exec_canonical.py | `Path(__file__).resolve().parent` | `from core import PROJECT_ROOT` |
| preflight_check.py → orchestration/preflight_check.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE` |
| retry_harness.py → pipeline/retry/retry_harness.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE_DIR` |
| validate_cases_v2.py → orchestration/validate_cases_v2.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE` |
| templates.py → pipeline/generation/templates.py | `Path(__file__).parent` | `from core import PROJECT_ROOT as BASE_DIR` |

**This is the ONLY logic change in the entire plan:** adding `PROJECT_ROOT` to core/__init__.py and updating the 9 path resolution lines. No function signatures, control flow, or behavior changes.

### YAML config path updates

125 config files in `configs/` reference case files. All must be updated:

```yaml
# BEFORE
source: "cases_v2.json"
source: "cases_v2_ffd.json"

# AFTER
source: "case_data/cases_v2.json"
source: "case_data/cases_v2_ffd.json"
```

Execution: `sed -i '' 's|source: "cases_|source: "data/cases_|g' configs/*.yaml`

Additional patterns to catch:
- `sed -i '' 's|source: cases_|source: data/cases_|g' configs/*.yaml` (unquoted)

### Scripts path updates

26 files in `scripts/` reference case files. Same sed pattern applies.

---

## 6. Import Rewrite Rules

1. **Absolute imports ONLY** from project root. No relative imports.
2. **Import format:** `from <module>.<submodule>.<file> import <name>`
3. **No `import <module>` for moved modules** — always `from <module> import <name>`

### Key import mappings

```python
# core
from core.config.constants import V2_CONDITIONS,

...
from core.config.experiment_config import get_config, ExperimentConfig
from core.contracts.contracts_v2 import ReasoningArtifactV2,

...
from core.registry.condition_registry import get_condition,

...
from core.registry.prompt_registry import get_component,

...
from core.llm import call_model
from core.code_assembly import CodeAssembler, AssemblyResult
from core.parse_types import ParsedGenerationV2
from core._stdlib import STDLIB_MODULES

# pipeline
from core.pipeline import build,

...
from core.pipeline import build_prompt,

...
from core.pipeline import extract_code_v2,

...
from core.pipeline.parsing import parse_generation_v2,

...
from core.pipeline import run_v2
from core.pipeline import run_case
from core.pipeline import run_retry_v2

# evaluation
from core.evaluation.evaluator_v2 import run_v2_classifier,

...
from core.evaluation import evaluate_case
from core.evaluation import compute_reasoning_correct,

...
from core.evaluation.reasoning_v2 import normalize_generation_v2,

...
from core.evaluation import compute_metrics_v2
from core.evaluation import run_execution,

...

# orchestration
from core.pipeline.orchestration.runner import main
from core.pipeline.orchestration import run_experiment

# logging_
from core.logging_.logging_core import EventLogger,

...
from core.logging_.call_logger import CallLogger
```

---

## 7. Validation Checklist

### Import resolution (after each phase)
- [ ] `python -c "from core.llm import call_model"`
- [ ] `python -c "from core.code_assembly import CodeAssembler"`
- [ ] `python -c "from core.parse_types import ParsedGenerationV2"`
- [ ] `python -c "from evaluation.evaluator_v2 import run_v2_classifier"`
- [ ] `python -c "from pipeline.execution.execution_v2 import run_v2"`
- [ ] `python -c "from orchestration.runner import main"`
- [ ] `python -c "from analysis.load_logs import load_logs"`

### CLI entrypoint
- [ ] `python run.py --help` works
- [ ] `python -m orchestration.runner --help` works

### Test discovery
- [ ] `python -m pytest tests/ --collect-only` finds tests
- [ ] `python -m pytest tests_v2/ --collect-only` finds tests

### Config loading
- [ ] `python -c "from core.config.experiment_config import load_config; load_config('configs/default.yaml')"`
- [ ] Case file path resolves: `Path('data/cases_v2.json').exists()`

### stdlib logging safety
- [ ] `python -c "import logging; logging.basicConfig(); from logging_.logging_core import EventLogger"` — no conflict

### Dependency direction
- [ ] `grep -r "from pipeline\|from orchestration\|from logging_\|from analysis" core/` — must return ZERO results
- [ ] `grep -r "from pipeline\|from orchestration\|from logging_" evaluation/` — must return ZERO results (except inside function bodies)
- [ ] `grep -r "from orchestration\|from logging_" pipeline/` — must return ZERO results

### Smoke test
- [ ] Run one experiment end-to-end with a 1-case config

---

## 8. Risk Mitigation

| Risk | Detection | Mitigation |
|---|---|---|
| `Path(__file__).parent` points to wrong dir after move | Phase 14 validation; smoke test | All replaced with `PROJECT_ROOT` |
| YAML configs still reference old case paths | `grep -r "source:.*cases_" configs/ \| grep -v "data/"` — must be empty | Bulk sed in Phase 14 |
| scripts/ imports break | `python -m py_compile scripts/*.py` after Phase 15 | Update imports in scripts/ |
| Test imports break | `pytest --collect-only` | Update imports in tests/ |
| Deferred imports in evaluation/ fail at runtime | Smoke test in Phase 15 | Deferred imports are called from pipeline context where deps are available |
| logging_ shadows stdlib logging | Phase 10 validation | Trailing underscore prevents collision; verified explicitly |
| Circular imports introduced | Each phase validates import resolution | Strict DAG enforcement — if any phase fails, STOP |
| Config sha256 changes (experiment_config validates config hash) | Smoke test | sha256 is computed from config content, not path — moving data files doesn't change config content |
