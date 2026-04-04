"""Launch full v2 ablation: 3 models × 1 trial, all in parallel."""

import subprocess
import sys
import time
from pathlib import Path

CONFIGS = [
    "config_storage/v2_full_nano_1t.yaml",
    "config_storage/v2_full_4omini_1t.yaml",
    "config_storage/v2_full_5mini_1t.yaml",
]

LOG_DIR = Path("logs/v2_full_ablation")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    procs = []
    print(f"Launching {len(CONFIGS)} models in parallel (8 workers each)...")
    t0 = time.monotonic()

    for cfg in CONFIGS:
        name = Path(cfg).stem
        stdout_f = open(LOG_DIR / f"{name}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"{name}_stderr.log", "w")
        cmd = [sys.executable, "runner.py", "--config", cfg]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((name, proc, stdout_f, stderr_f))
        print(f"  {name} launched (pid={proc.pid})")
        time.sleep(2)

    print(f"\nWaiting for all models to complete...")
    print(f"  Monitor: .venv/bin/python scripts/live_dashboard_v2.py logs/v2_full_ablation")
    print()

    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  {name}: {status}")

    elapsed = time.monotonic() - t0
    print(f"\nAll models finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Build cross-model merged_run.jsonl
    print("\nBuilding cross-model merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(
            str(LOG_DIR),
            strict_completeness=False,
            strict_schema=False,
        )
        import json
        rows = [json.loads(l) for l in open(path)]
        models = set(r.get("model") for r in rows)
        conds = set(r.get("condition") for r in rows)
        print(f"  {len(rows)} total rows, {len(models)} models, {len(conds)} conditions")
    except Exception as e:
        print(f"  Cross-model merge failed: {e}")

    # Final dashboard
    print("\nWriting final dashboard...")
    try:
        import json
        from core.logging_.v2_metrics import compute_v2_metrics
        from core.logging_.v2_dashboard import write_v2_dashboard
        rows = [json.loads(l) for l in open(path)]
        metrics = compute_v2_metrics(rows, expected_cases=58, expected_conditions=3)
        write_v2_dashboard(metrics, LOG_DIR / "dashboard_v2_final.txt")
        print(f"  Dashboard: {LOG_DIR / 'dashboard_v2_final.txt'}")
    except Exception as e:
        print(f"  Dashboard failed: {e}")


if __name__ == "__main__":
    main()
