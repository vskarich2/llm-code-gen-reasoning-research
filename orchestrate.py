"""Experiment orchestrator for T3 benchmark.

Replaces bash scripts with a Python-based, config-driven, process-parallel runner.

Usage:
    .venv/bin/python orchestrate.py --config experiments/my_experiment.yaml
    .venv/bin/python orchestrate.py --config experiments/my_experiment.yaml --dry-run
"""

import argparse
import json
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from logging_core import OrchestratorLogger, write_json_atomic


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass(frozen=True)
class WorkItem:
    run_dir: str
    run_id: str
    model: str
    condition: str
    trial: int


@dataclass
class RunResult:
    pass_rate: float
    stats: dict


# ============================================================
# CONFIG LOADING
# ============================================================

def load_experiment_config(config_path: str) -> dict:
    """Load and validate experiment YAML config."""
    import yaml
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)

    # Validate required sections
    required = {"experiment", "models", "conditions", "trials", "cases", "execution", "output"}
    missing = required - set(config.keys())
    if missing:
        raise ValueError(f"Config missing sections: {missing}")

    # Validate models
    gen_models = config["models"].get("generation", [])
    if not gen_models:
        raise ValueError("No generation models specified")
    for m in gen_models:
        if not isinstance(m, dict) or "name" not in m:
            raise ValueError(f"Invalid model spec: {m}")

    # Validate conditions
    if not config["conditions"]:
        raise ValueError("No conditions specified")

    # Validate trials
    if not isinstance(config["trials"], int) or config["trials"] < 1:
        raise ValueError(f"trials must be >= 1, got {config['trials']}")

    # Validate parallelism
    par = config["execution"].get("parallelism", 1)
    if not isinstance(par, int) or par < 1 or par > 32:
        raise ValueError(f"parallelism must be 1-32, got {par}")

    # Validate cases file
    cases_file = config["cases"].get("source", "cases_v2.json")
    if not Path(cases_file).exists():
        raise ValueError(f"Cases file not found: {cases_file}")

    return config


def get_config_hash(config: dict) -> str:
    import hashlib
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ============================================================
# PREFLIGHT
# ============================================================

def run_preflight(config: dict, logger: OrchestratorLogger) -> None:
    """Run all preflight checks. Logs results. Raises on failure."""
    cases_file = config["cases"].get("source", "cases_v2.json")

    # Check 1: Cases file exists and has cases
    cases = json.loads(Path(cases_file).read_text())
    if not cases:
        raise RuntimeError("Cases file is empty")
    logger.log_event("orchestrator.preflight_pass", {
        "check": "cases_loaded", "count": len(cases),
    })
    print(f"  Preflight: {len(cases)} cases loaded", flush=True)

    # Check 2: Evaluator sanity (reference fix for canary case passes)
    try:
        sys.path.insert(0, ".")
        from exec_eval import exec_evaluate
        from validate_cases_v2 import load_reference_code

        canary = next(c for c in cases if c["id"] == "alias_config_a")
        canary["code_files_contents"] = {}
        for rel in canary["code_files"]:
            canary["code_files_contents"][rel] = Path(rel).read_text()
        ref = load_reference_code(canary)
        result = exec_evaluate(canary, ref)
        if not result["pass"]:
            raise RuntimeError(f"Canary case failed: {result.get('reasons')}")
        logger.log_event("orchestrator.preflight_pass", {
            "check": "evaluator_sanity", "canary": "alias_config_a",
        })
        print("  Preflight: evaluator sanity PASS", flush=True)
    except Exception as e:
        logger.log_event("orchestrator.preflight_fail", {
            "check": "evaluator_sanity", "error": str(e),
        })
        raise RuntimeError(f"Evaluator sanity failed: {e}")


# ============================================================
# WORK ITEM GENERATION
# ============================================================

def generate_work_items(config: dict, experiment_dir: Path) -> list[WorkItem]:
    models = config["models"]["generation"]
    conditions = config["conditions"]
    trials = config["trials"]

    items = []
    for model_spec in models:
        model_name = model_spec["name"]
        for condition in conditions:
            for trial in range(1, trials + 1):
                run_id = f"{model_name}_{condition}_t{trial}_{uuid.uuid4().hex[:8]}"
                run_dir = experiment_dir / model_name / condition / f"trial_{trial}"
                items.append(WorkItem(
                    run_dir=str(run_dir),
                    run_id=run_id,
                    model=model_name,
                    condition=condition,
                    trial=trial,
                ))
    return items


# ============================================================
# WORKER (runs in child process)
# ============================================================

def run_single(run_dir: str, run_id: str, model: str,
               condition: str, trial: int, config: dict) -> RunResult:
    """Execute one (model, condition, trial) run inside a worker process.

    Creates RunLogger LOCALLY — never passed from orchestrator.
    """
    from logging_core import RunLogger

    logger = RunLogger(
        run_dir=Path(run_dir),
        run_id=run_id,
        model=model,
        condition=condition,
        trial=trial,
    )

    sys.path.insert(0, ".")
    from runner import load_cases
    from execution import build_prompt, evaluate_case, set_call_context
    from llm import call_model

    cases_file = config["cases"].get("source", "cases_v2.json")
    max_cases = config["cases"].get("max_cases", 0)
    cases = load_cases(cases_file=cases_file)
    if max_cases and max_cases > 0:
        cases = cases[:max_cases]

    logger.log_event("run.start", {
        "total_cases": len(cases),
        "config_hash": get_config_hash(config),
        "model": model,
        "condition": condition,
    }, phase="run")

    for case in cases:
        case_id = case["id"]
        trace_id = logger.start_case(case_id)

        try:
            # Build prompt
            prompt, op_used = build_prompt(case, condition)

            # Generate
            gen_start = time.monotonic()
            file_paths = list(case.get("code_files_contents", {}).keys()) or None
            raw_output = call_model(prompt, model=model, file_paths=file_paths)
            gen_elapsed = time.monotonic() - gen_start

            logger.log_call(
                model=model,
                prompt=prompt,
                response=raw_output,
                elapsed_seconds=gen_elapsed,
                case_id=case_id,
                phase="generation",
            )

            # Parse + Reconstruct + Evaluate (uses existing pipeline)
            case["_condition"] = condition
            parsed, ev = evaluate_case(case, raw_output)

            logger.log_event("parse.result", {
                "format": parsed.get("response_format"),
                "error": parsed.get("parse_error"),
            }, case_id=case_id, phase="parsing")

            logger.log_event("execution.result", {
                "pass": ev["pass"],
                "score": ev["score"],
                "ran": ev.get("execution", {}).get("ran"),
            }, case_id=case_id, phase="evaluation")

            # End case
            logger.end_case(case_id, {
                "pass": ev["pass"],
                "score": ev["score"],
                "code_correct": ev.get("code_correct"),
                "reasoning_correct": ev.get("reasoning_correct"),
                "failure_type": ev.get("failure_type"),
            })

        except Exception as e:
            logger.fail_case(case_id, {
                "error": f"{type(e).__name__}: {e}",
            })

    stats = logger.finalize()
    return RunResult(pass_rate=stats["pass_rate"], stats=stats)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="T3 Experiment Orchestrator")
    parser.add_argument("--config", required=True, help="Experiment config YAML")
    parser.add_argument("--dry-run", action="store_true", help="Show work items without running")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    config_hash = get_config_hash(config)
    exp_name = config["experiment"]["name"]
    base_dir = Path(config["output"].get("base_dir", "experiments"))
    experiment_dir = base_dir / exp_name

    print(f"Experiment: {exp_name}", flush=True)
    print(f"Config hash: {config_hash}", flush=True)

    # Freeze config
    experiment_dir.mkdir(parents=True, exist_ok=True)
    import yaml
    with open(experiment_dir / "experiment.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    # Orchestrator logger
    orch_logger = OrchestratorLogger(experiment_dir)
    orch_logger.log_event("orchestrator.start", {
        "config_hash": config_hash,
        "experiment_name": exp_name,
        "models": [m["name"] for m in config["models"]["generation"]],
        "conditions": config["conditions"],
        "trials": config["trials"],
        "parallelism": config["execution"].get("parallelism", 1),
    })

    # Preflight
    try:
        run_preflight(config, orch_logger)
    except RuntimeError as e:
        orch_logger.log_event("orchestrator.abort", {"reason": str(e)})
        orch_logger.close()
        print(f"ABORT: {e}", flush=True)
        sys.exit(1)

    # Generate work items
    work_items = generate_work_items(config, experiment_dir)
    for item in work_items:
        orch_logger.log_event("orchestrator.schedule", {
            "run_id": item.run_id,
            "model": item.model,
            "condition": item.condition,
            "trial": item.trial,
            "run_dir": item.run_dir,
        })

    total = len(work_items)
    print(f"Scheduled: {total} work items", flush=True)

    if args.dry_run:
        print("DRY RUN — not executing", flush=True)
        for item in work_items:
            print(f"  {item.run_id} → {item.run_dir}", flush=True)
        orch_logger.log_event("orchestrator.abort", {"reason": "dry_run"})
        orch_logger.close()
        return

    # Execute
    manifest = {}
    completed_count = 0
    failed_count = 0
    parallelism = config["execution"].get("parallelism", 1)

    with ProcessPoolExecutor(max_workers=min(parallelism, total)) as pool:
        futures = {
            pool.submit(
                run_single,
                run_dir=item.run_dir,
                run_id=item.run_id,
                model=item.model,
                condition=item.condition,
                trial=item.trial,
                config=config,
            ): item
            for item in work_items
        }

        done = 0
        for future in as_completed(futures):
            item = futures[future]
            done += 1
            try:
                result = future.result()
                completed_count += 1
                orch_logger.log_event("orchestrator.worker_end", {
                    "run_id": item.run_id,
                    "status": "completed",
                    "pass_rate": result.pass_rate,
                    "total_cases": result.stats.get("total_cases", 0),
                })
                manifest[item.run_id] = {
                    "status": "completed",
                    "pass_rate": result.pass_rate,
                }
                print(
                    f"[{done}/{total}] {item.run_id} DONE ({result.pass_rate:.1%})",
                    flush=True,
                )
            except Exception as e:
                failed_count += 1
                orch_logger.log_event("orchestrator.worker_failed", {
                    "run_id": item.run_id,
                    "error": f"{type(e).__name__}: {e}",
                })
                manifest[item.run_id] = {
                    "status": "failed",
                    "error": str(e),
                }
                print(
                    f"[{done}/{total}] {item.run_id} FAILED: {e}",
                    flush=True,
                )

    write_json_atomic(experiment_dir / "manifest.json", manifest)

    orch_logger.log_event("orchestrator.complete", {
        "total": total,
        "completed": completed_count,
        "failed": failed_count,
    })
    orch_logger.close()

    print(f"\nExperiment complete: {completed_count} succeeded, {failed_count} failed", flush=True)


if __name__ == "__main__":
    main()
