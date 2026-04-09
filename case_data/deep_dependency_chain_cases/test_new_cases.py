"""Smoke tests for the 6 new deep dependency chain cases.

Verifies:
1. Buggy pipeline runs without error
2. Bug is visible in output (observable symptom present)
3. build_case() loads without error
4. Chain has correct structure

Run: .venv/bin/python case_data/deep_dependency_chain_cases/test_new_cases.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return condition


def test_auth_context():
    print("auth_context:")
    from case_data.deep_dependency_chain_cases.auth_context.generated_cases.auth_context.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.auth_context.cases.case_auth_context import build_case

    result = run_pipeline()
    # Bug: org_id stripped, alice falls to default tier, write denied
    check("pipeline runs", isinstance(result, dict))
    check("bug: org_id stripped", result["org_id"] == "100", f"org_id={result['org_id']!r}")
    check("bug: wrong tier (default)", result["tier"] == "default", f"tier={result['tier']!r}")
    check("bug: write denied", result["granted"] is False, f"granted={result['granted']}")

    spec = build_case()
    check("spec loads", spec.case_id == "auth_context_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_billing_aggregation():
    print("billing_aggregation:")
    from case_data.deep_dependency_chain_cases.billing_aggregation.generated_cases.billing_aggregation.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.billing_aggregation.cases.case_billing_aggregation import build_case

    result = run_pipeline()
    # Bug: 85 units (local date) instead of 100 (UTC) -> growth instead of enterprise
    check("pipeline runs", isinstance(result, dict))
    check("bug: undercounted units", result["units"] == 85, f"units={result['units']}")
    check("bug: wrong tier (growth)", result["tier"] == "growth", f"tier={result['tier']!r}")
    check("bug: invoice total $8.50", abs(result["total"] - 8.50) < 0.01, f"total={result['total']}")

    spec = build_case()
    check("spec loads", spec.case_id == "billing_aggregation_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_config_derivation():
    print("config_derivation:")
    from case_data.deep_dependency_chain_cases.config_derivation.generated_cases.config_derivation.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.config_derivation.cases.case_config_derivation import build_case

    result = run_pipeline()
    # Bug: port is string, pool_size = string repeat -> service error
    check("pipeline runs", isinstance(result, dict))
    check("bug: service error", result["status"] == "error", f"status={result['status']!r}")
    check("bug: pool_size is string", isinstance(result["pool_size"], str), f"pool_size={result['pool_size']!r}")

    spec = build_case()
    check("spec loads", spec.case_id == "config_derivation_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_event_etl():
    print("event_etl:")
    from case_data.deep_dependency_chain_cases.event_etl.generated_cases.event_etl.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.event_etl.cases.case_event_etl import build_case

    result = run_pipeline()
    # Bug: user_id lowercased, enricher can't find user -> tier=unknown
    check("pipeline runs", isinstance(result, list))
    check("bug: user_id lowercased", result[0]["user_id"] == "alice_smith",
          f"user_id={result[0]['user_id']!r}")
    check("bug: tier unknown", result[0]["tier"] == "unknown", f"tier={result[0]['tier']!r}")
    check("bug: all users unknown", all(e["tier"] == "unknown" for e in result))

    spec = build_case()
    check("spec loads", spec.case_id == "event_etl_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_search_index():
    print("search_index:")
    from case_data.deep_dependency_chain_cases.search_index.generated_cases.search_index.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.search_index.cases.case_search_index import build_case

    result = run_pipeline()
    index = result["index"]
    # Bug: metadata tokens (alice, bob, carol) in index
    check("pipeline runs", isinstance(result, dict))
    check("bug: author in index", "alice" in index, f"alice in index={('alice' in index)}")
    check("bug: doc id in index", "doc1" in index, f"doc1 in index={('doc1' in index)}")
    # Content should still work
    check("content token present", "python" in index, f"python in index={('python' in index)}")

    spec = build_case()
    check("spec loads", spec.case_id == "search_index_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_serialization_pipeline():
    print("serialization_pipeline:")
    from case_data.deep_dependency_chain_cases.serialization_pipeline.generated_cases.serialization_pipeline.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.serialization_pipeline.cases.case_serialization_pipeline import build_case

    result = run_pipeline()
    # Bug: created_at is epoch int, not ISO string
    check("pipeline runs", isinstance(result, dict))
    check("bug: sent=3", result["sent"] == 3, f"sent={result['sent']}")
    check("bug: timestamps are ints", all(isinstance(t, int) for t in result["timestamps"]),
          f"types={result['timestamp_types']}")
    check("bug: no T in timestamps", all("T" not in str(t) for t in result["timestamps"]))

    spec = build_case()
    check("spec loads", spec.case_id == "serialization_pipeline_chain")
    check("chain length", len(spec.chain) == 4)
    check("traps present", len(spec.traps) >= 4)


def test_logging_pipeline():
    print("logging_pipeline:")
    from case_data.deep_dependency_chain_cases.logging_pipeline.generated_cases.logging_pipeline.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.logging_pipeline.cases.case_logging_pipeline import build_case

    result = run_pipeline()
    # Bug: severity truncated to 4 chars (CRIT, WARN) -> not found in SEVERITY_LEVELS
    check("pipeline runs", isinstance(result, dict))
    check("bug: critical_count=0", result["critical_count"] == 0,
          f"critical_count={result['critical_count']}")
    check("bug: UNKNOWN events exist", result["breakdown"].get("UNKNOWN", 0) > 0,
          f"breakdown={result['breakdown']}")

    spec = build_case()
    check("spec loads", spec.case_id == "logging_pipeline_chain")
    check("chain length", len(spec.chain) == 4)


def test_ml_feature():
    print("ml_feature:")
    from case_data.deep_dependency_chain_cases.ml_feature.generated_cases.ml_feature.pipeline import run_pipeline
    from case_data.deep_dependency_chain_cases.ml_feature.cases.case_ml_feature import build_case

    result = run_pipeline()
    # Bug: window_size - 1 used instead of window_size -> wrong rolling mean
    check("pipeline runs", isinstance(result, dict))
    check("bug: score present", "score" in result)
    # Correct rolling mean over window=3: (30+40+50)/3=40. Buggy window=2: (40+50)/2=45.
    # Buggy scaled = (45-30)/15 = 1.0. Score = 0.5 + 0.3*1.0 = 0.8. Correct = 0.5+0.3*0.667=0.7
    check("bug: wrong score (off by window)", result["score"] != round(0.5 + 0.3 * ((40.0 - 30.0) / 15.0), 4),
          f"score={result['score']}")

    spec = build_case()
    check("spec loads", spec.case_id == "ml_feature_chain")
    check("chain length", len(spec.chain) == 4)


if __name__ == "__main__":
    tests = [
        test_auth_context,
        test_billing_aggregation,
        test_config_derivation,
        test_event_etl,
        test_search_index,
        test_serialization_pipeline,
        test_logging_pipeline,
        test_ml_feature,
    ]
    failures = 0
    for t in tests:
        t()
        print()
    print("done")
