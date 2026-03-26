"""Retry harness — trajectory-level probe of reasoning-execution dynamics.

Scientific measurement instrument. NOT a production retry system.

Architecture:
  (Contractor) → Generator → Executor → Critic → Classify → [retry]

Three conditions:
  retry_no_contract   — pure baseline + test feedback
  retry_with_contract — baseline + contract context on retry
  retry_adaptive      — baseline + failure-type-specific hints (confidence-gated)

Control vs Analysis separation:
  CONTROL signals (used in retry loop): consecutive_same_failure, similarity, score_improving
  ANALYSIS signals (post-hoc only): trajectory_dynamics, transition_entropy, oscillation_rate
"""

import difflib
import hashlib
import json
import logging
import math
import re
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from llm import call_model, get_model_config
from parse import extract_code
from evaluator import evaluate_output, compute_alignment
from prompts import build_base_prompt, _format_code_files

_log = logging.getLogger("t3.retry")

BASE_DIR = Path(__file__).parent

MAX_ITERATION_SECONDS = 60
MAX_TOTAL_SECONDS = 360

# Parameterized thresholds (no magic numbers in control logic)
SIMILARITY_THRESHOLD = 0.95
SCORE_EPSILON = 0.05
PERSISTENCE_ESCALATION_COUNT = 2

# Adaptive retry hints per failure type
ADAPTIVE_HINTS = {
    "TEMPORAL_ORDERING": "Carefully check ordering of operations and when values are computed relative to modifications.",
    "HIDDEN_DEPENDENCY": "Identify any implicit dependencies or shared state that may be affected by your changes.",
    "INVARIANT_VIOLATION": "Ensure all invariants (consistency, conservation, constraints) are preserved.",
    "PARTIAL_STATE_UPDATE": "Ensure all related state variables are updated consistently, not just one component.",
    "RETRY_LOGIC_BUG": "Check for duplicated operations, missing idempotency, or incorrect retry assumptions.",
    "LOGGING_INCONSISTENCY": "Verify that logging and side effects are consistent with the intended operation order.",
    "CONFOUNDING_LOGIC": "Re-evaluate your assumptions and identify the root cause of failure.",
    "EDGE_CASE_MISSED": "Consider edge cases and boundary conditions that your fix may not handle.",
    "UNKNOWN": "Re-evaluate your assumptions and identify the root cause of failure.",
}

# Latent correctness signal keywords
_LATENT_KEYWORDS = {
    "TEMPORAL_ORDERING": ["order", "before", "after", "sequence", "timing", "first"],
    "HIDDEN_DEPENDENCY": ["dependency", "import", "missing", "undefined", "hidden"],
    "INVARIANT_VIOLATION": ["invariant", "balance", "conservation", "consistent", "atomic"],
    "PARTIAL_STATE_UPDATE": ["partial", "incomplete", "all fields", "both"],
    "RETRY_LOGIC_BUG": ["retry", "duplicate", "idempotent", "once", "exactly once"],
}


# ============================================================
# GENERIC WORDS (filtered from critique accuracy matching)
# ============================================================

_GENERIC_WORDS = frozenset({
    "value", "list", "index", "error", "function", "code", "line",
    "variable", "return", "should", "does", "instead", "because",
    "need", "change", "update", "method", "class", "object", "type",
    "result", "data", "input", "output", "true", "false", "none",
    "with", "from", "that", "this", "have", "been", "will", "when",
})


# ============================================================
# PURE HELPER FUNCTIONS
# ============================================================

def _select_best_code(strict_code: str, fallback_code: str
                      ) -> tuple[str, str, bool, dict]:
    """Select best code from strict and fallback extraction candidates.

    Returns (selected_code, extraction_source, extraction_conflict, extraction_candidates).

    Selection criteria (applied only when two DIFFERENT non-empty candidates):
      C1: Syntax validity (ast.parse succeeds)
      C2: Non-trivial (len >= 50 and contains 'def ' or 'class ')
      C3: Length tiebreaker (longer wins)
    """
    import ast

    candidates = []
    if strict_code and strict_code.strip():
        candidates.append(("strict", strict_code))
    if fallback_code and fallback_code.strip() and fallback_code.strip() != strict_code.strip():
        candidates.append(("fallback", fallback_code))

    extraction_candidates = {src: len(code) for src, code in candidates}

    if len(candidates) == 0:
        return ("", "none", False, {})
    if len(candidates) == 1:
        return (candidates[0][1], candidates[0][0], False, extraction_candidates)

    # Two different non-empty candidates — apply C1-C3
    extraction_conflict = True

    # C1: Filter to syntax-valid
    valid = []
    for src, code in candidates:
        try:
            ast.parse(code)
            valid.append((src, code))
        except SyntaxError:
            pass

    if len(valid) == 0:
        return (candidates[0][1], candidates[0][0], True, extraction_candidates)
    if len(valid) == 1:
        return (valid[0][1], valid[0][0], True, extraction_candidates)

    # C2: Filter to non-trivial
    nontrivial = []
    for src, code in valid:
        has_def = 'def ' in code or 'class ' in code
        long_enough = len(code.strip()) >= 50
        if has_def and long_enough:
            nontrivial.append((src, code))

    if len(nontrivial) == 0:
        return (valid[0][1], valid[0][0], True, extraction_candidates)
    if len(nontrivial) == 1:
        return (nontrivial[0][1], nontrivial[0][0], True, extraction_candidates)

    # C3: Tiebreaker — longer code
    best = max(nontrivial, key=lambda x: len(x[1]))
    return (best[1], best[0], True, extraction_candidates)


def _normalize(code: str) -> str:
    """Strip trailing whitespace per line and leading/trailing newlines."""
    return "\n".join(line.rstrip() for line in code.strip().splitlines())


def _compute_diff(old_code, new_code):
    """Compute structured diff between two code strings.

    edit_dispersion = 1/hunks (PROXY metric, not true locality).
    """
    if not old_code or not new_code:
        return {"lines_changed": 0, "chars_changed": 0, "hunks": 0,
                "diff_text": "", "edit_dispersion": 1.0}

    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, n=0))

    lines_changed = sum(1 for l in diff if l.startswith(('+', '-'))
                        and not l.startswith(('+++', '---')))
    chars_changed = (sum(1 for a, b in zip(old_code, new_code) if a != b)
                     + abs(len(new_code) - len(old_code)))

    hunks = sum(1 for l in diff if l.startswith('@@'))
    edit_dispersion = round(1.0 / max(hunks, 1), 3)

    return {
        "lines_changed": lines_changed,
        "chars_changed": chars_changed,
        "hunks": hunks,
        "edit_dispersion": edit_dispersion,
        "diff_text": "".join(diff[:50]),
    }


def _is_stagnated(diff, current_score, prev_score):
    """True if edit is tiny AND score did not improve."""
    if not diff:
        return False
    return diff["chars_changed"] < 10 and current_score <= prev_score


def _keyword_overlap(text_a, text_b):
    """Jaccard similarity on significant words (>2 chars, no stop words)."""
    stop = {"the", "a", "an", "is", "it", "to", "of", "in", "and", "for", "that", "this"}
    words_a = {w.lower() for w in text_a.split() if len(w) > 2 and w.lower() not in stop}
    words_b = {w.lower() for w in text_b.split() if len(w) > 2 and w.lower() not in stop}
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _build_error_object(ev):
    """Build structured error from evaluation result."""
    ex = ev.get("execution", {})
    reasons = ev.get("reasons", [])

    if ex.get("syntax_error"):
        category, message = "syntax", str(ex["syntax_error"])
    elif ex.get("runtime_error") or ex.get("error_message"):
        category, message = "runtime", str(ex.get("error_message", "unknown"))
    elif not ex.get("ran"):
        category, message = "load", "could not load module"
    elif not ex.get("invariant_pass"):
        category, message = "logic", "; ".join(reasons[:3])
    elif not ex.get("mutation_pass"):
        category, message = "spec", "; ".join(reasons[:3])
    else:
        category = "unknown"
        message = "; ".join(reasons[:3]) if reasons else "unknown"

    return {
        "type": category,
        "message": message,
        "category": category,
        "passed_tests": ex.get("passed_tests", 0),
        "total_tests": ex.get("total_tests", 0),
        "reasons": reasons,
    }


def _format_test_output(ev):
    """Format evaluation result as human-readable test output for retry prompt."""
    lines = []
    ex = ev.get("execution", {})
    if ex.get("syntax_error"):
        lines.append(f"SYNTAX ERROR: {ex['syntax_error']}")
    elif ex.get("error_message"):
        lines.append(f"RUNTIME ERROR: {ex['error_message']}")
    elif not ex.get("ran"):
        lines.append("CODE DID NOT RUN (could not load module)")
    for r in ev.get("reasons", []):
        lines.append(f"- {r}")
    passed = ex.get("passed_tests", 0)
    total = ex.get("total_tests", 0)
    lines.append(f"\nStatus: FAILED ({passed}/{total} tests passed)")
    return "\n".join(lines)


def _infer_failure_mode(error_obj, diff, critique):
    """Predict failure mode from error/critique signals. NOT ground truth."""
    category = error_obj.get("category", "unknown")
    if category in ("syntax", "runtime", "load"):
        return f"{category}_error"

    if critique and critique.get("_valid", True):  # default True if _valid not set
        inv = (critique.get("invariant_violated") or "").lower()
        if "order" in inv or "before" in inv:
            return "ordering"
        if "mutat" in inv or "alias" in inv or "copy" in inv:
            return "aliasing"
        if "conserv" in inv or "balance" in inv:
            return "conservation"
        if "duplic" in inv or "retry" in inv or "idempot" in inv:
            return "duplication"

    msg = error_obj.get("message", "").lower()
    if "mutated" in msg or "defaults" in msg:
        return "aliasing"
    if "stale" in msg or "order" in msg:
        return "ordering"
    if "duplicate" in msg:
        return "duplication"
    if "conservation" in msg or "merchant" in msg:
        return "conservation"

    return "unknown"


def _clean_critique_for_log(critique):
    """Remove internal keys (prefixed with _) before logging."""
    if critique is None:
        return None
    return {k: v for k, v in critique.items() if not k.startswith("_")}


def _estimate_reasoning_validity(critique, reasoning_k, case, raw_output, trajectory, k):
    """Estimate reasoning validity from independent signals.

    critique_signal is LOGGED but NOT included in the estimate.
    Only heuristic_signal and trajectory_signal contribute.
    """
    from evaluator import _detected_correct_reasoning

    # Signal 1: heuristic keyword match
    heuristic_signal = _detected_correct_reasoning(case, raw_output)

    # Signal 2: trajectory consistency
    trajectory_signal = None
    if k > 0 and trajectory:
        prev = trajectory[-1].get("reasoning", "")
        if prev and reasoning_k:
            trajectory_signal = _keyword_overlap(prev, reasoning_k) > 0.5

    # Signal 3: critique (logged only, NOT in estimate)
    critique_signal = None
    if critique and critique.get("_valid") and critique.get("is_reasoning_error") is not None:
        critique_signal = not critique["is_reasoning_error"]

    # Estimate from heuristic + trajectory only
    non_critique = [s for s in [heuristic_signal, trajectory_signal] if s is not None]
    estimated = sum(non_critique) / len(non_critique) >= 0.5 if non_critique else None

    return {
        "estimated_valid": estimated,
        "heuristic_signal": heuristic_signal,
        "trajectory_signal": trajectory_signal,
        "critique_signal": critique_signal,
    }


# ============================================================
# TRAJECTORY HELPERS (new — trajectory-aware analysis)
# ============================================================

def _detect_latent_signal(reasoning_k, code_passed):
    """Detect when model 'knows the answer' but fails to execute."""
    if code_passed:
        return {"correct_pattern_in_reasoning": False, "latent_reasoning_type": None}
    reasoning_lower = reasoning_k.lower()
    for ftype, keywords in _LATENT_KEYWORDS.items():
        if any(kw in reasoning_lower for kw in keywords):
            return {"correct_pattern_in_reasoning": True, "latent_reasoning_type": ftype}
    return {"correct_pattern_in_reasoning": False, "latent_reasoning_type": None}


def _compute_transitions(failure_sequence):
    """Count consecutive failure type transitions."""
    transitions = {}
    for i in range(len(failure_sequence) - 1):
        if failure_sequence[i] and failure_sequence[i + 1]:
            key = f"{failure_sequence[i]}→{failure_sequence[i+1]}"
            transitions[key] = transitions.get(key, 0) + 1
    return transitions


def _compute_transition_entropy(transitions):
    """Shannon entropy over transition distribution."""
    if not transitions:
        return 0.0
    total = sum(transitions.values())
    probs = [c / total for c in transitions.values()]
    return round(-sum(p * math.log2(p) for p in probs if p > 0), 3)


def _count_reversals(scores):
    """Count score direction changes."""
    return sum(1 for i in range(2, len(scores))
               if (scores[i - 1] - scores[i - 2]) * (scores[i] - scores[i - 1]) < 0)


def _run_lengths(sequence):
    """Lengths of consecutive identical runs."""
    if not sequence:
        return []
    lengths = []
    current = 1
    for i in range(1, len(sequence)):
        if sequence[i] == sequence[i - 1]:
            current += 1
        else:
            lengths.append(current)
            current = 1
    lengths.append(current)
    return lengths


def _classify_trajectory_dynamics(trajectory):
    """ANALYSIS ONLY — classify trajectory pattern. NOT used for control."""
    if len(trajectory) <= 1:
        return {"pattern": "single_shot", "oscillation": False,
                "divergence": False, "stagnation": False, "convergence": False,
                "score_reversals": 0, "type_changes": 0, "max_consecutive_similar": 0}

    scores = [e["score"] for e in trajectory]
    types = [e.get("failure_type") for e in trajectory if not e["pass"]]
    sims = [e.get("similarity_to_previous") for e in trajectory[1:]
            if e.get("similarity_to_previous") is not None]

    reversals = _count_reversals(scores)
    oscillation = reversals >= 2

    type_changes = sum(1 for i in range(1, len(types)) if types[i] != types[i - 1]) if len(types) > 1 else 0
    no_improvement = scores[-1] <= scores[0]
    divergence = type_changes >= 2 and no_improvement

    consec_stag = 0
    max_stag = 0
    for s in sims:
        if s and s > SIMILARITY_THRESHOLD:
            consec_stag += 1
            max_stag = max(max_stag, consec_stag)
        else:
            consec_stag = 0
    stagnation = max_stag >= 2

    convergence = trajectory[-1]["pass"] and scores[-1] > scores[0]

    if convergence:
        pattern = "MONOTONIC_FIX" if not oscillation else "OSCILLATING_FIX"
    elif oscillation:
        pattern = "OSCILLATION"
    elif divergence:
        pattern = "DIVERGENCE"
    elif stagnation:
        pattern = "STAGNATION"
    else:
        pattern = "UNCLASSIFIED"

    return {
        "pattern": pattern, "oscillation": oscillation,
        "divergence": divergence, "stagnation": stagnation,
        "convergence": convergence, "score_reversals": reversals,
        "type_changes": type_changes, "max_consecutive_similar": max_stag,
    }


def _compute_convergence_depth(trajectory):
    """How deep into retry budget before success. 0.0=first, null=never."""
    if not trajectory:
        return None
    for i, e in enumerate(trajectory):
        if e["pass"]:
            return round(i / max(len(trajectory) - 1, 1), 3) if i > 0 else 0.0
    return None


def _trajectory_stability_score(failure_sequence):
    """1.0 = same type throughout, 0.0 = different every time."""
    types = [t for t in failure_sequence if t is not None]
    if len(types) <= 1:
        return 1.0
    changes = sum(1 for i in range(1, len(types)) if types[i] != types[i - 1])
    return round(1.0 - changes / (len(types) - 1), 3)


def _oscillation_rate(trajectory):
    """Fraction of score direction reversals."""
    scores = [e["score"] for e in trajectory]
    if len(scores) < 3:
        return 0.0
    reversals = _count_reversals(scores)
    return round(reversals / (len(scores) - 2), 3)


def _local_vs_global_ratio(trajectory):
    """Fraction of single-hunk (localized) edits."""
    diffs = [e["diff"] for e in trajectory[1:] if e.get("diff")]
    if not diffs:
        return None
    local = sum(1 for d in diffs if d.get("hunks", 0) == 1)
    return round(local / len(diffs), 3)


def _compute_failure_persistence(failure_type_sequence, error_messages=None):
    """Measures how stuck the model is on one failure type. Robust to classifier noise."""
    types = [t for t in failure_type_sequence if t is not None]
    if not types:
        return {"longest_run": 0, "dominant_fraction": 0.0,
                "dominant_type": None, "unknown_rate": 0.0}

    unknown_count = sum(1 for t in types if t == "UNKNOWN")

    # Noise correction: replace UNKNOWN with neighbor if error messages are similar
    corrected = list(types)
    if error_messages and unknown_count > 0:
        msgs = [m or "" for m in error_messages]
        for i in range(len(corrected)):
            if corrected[i] == "UNKNOWN" and i < len(msgs):
                for j in range(i - 1, -1, -1):
                    if corrected[j] != "UNKNOWN" and j < len(msgs):
                        if msgs[j] and msgs[i] and SequenceMatcher(None, msgs[j], msgs[i]).ratio() > 0.8:
                            corrected[i] = corrected[j]
                        break

    longest = 1
    current = 1
    for i in range(1, len(corrected)):
        if corrected[i] == corrected[i - 1] and corrected[i] != "UNKNOWN":
            current += 1
            longest = max(longest, current)
        else:
            current = 1

    non_unknown = [t for t in corrected if t != "UNKNOWN"]
    if non_unknown:
        counts = Counter(non_unknown)
        dominant_type, dominant_count = counts.most_common(1)[0]
        dominant_fraction = round(dominant_count / len(types), 3)
    else:
        dominant_type = None
        dominant_fraction = 0.0

    return {
        "longest_run": longest,
        "dominant_fraction": dominant_fraction,
        "dominant_type": dominant_type,
        "unknown_rate": round(unknown_count / len(types), 3),
    }


def _leg_rate(trajectory, field):
    """Compute LEG rate for a given boolean field."""
    failed = [e for e in trajectory if not e.get("pass", True)]
    if not failed:
        return 0.0
    leg_count = sum(1 for e in failed if e.get(field))
    return round(leg_count / len(failed), 3)


def _leg_resolution(trajectory, field):
    """Compute LEG resolution rate: LEG(k) ∧ pass(k+1) / LEG(k)."""
    leg_events = 0
    resolved = 0
    for i in range(len(trajectory)):
        if trajectory[i].get(field):
            leg_events += 1
            if i + 1 < len(trajectory) and trajectory[i + 1].get("pass"):
                resolved += 1
    if leg_events == 0:
        return None
    return round(resolved / leg_events, 3)


def _eval_parse_rate(trajectory, error_field):
    """Compute evaluator parse failure rate."""
    attempted = sum(1 for e in trajectory if not e.get("pass", True) and e.get("reasoning"))
    if attempted == 0:
        return 0.0
    failures = sum(1 for e in trajectory if e.get(error_field) is not None)
    return round(failures / attempted, 3)


def _compute_eval_bias(trajectory):
    """Wrapper for compute_evaluator_bias."""
    from leg_evaluator import compute_evaluator_bias
    return compute_evaluator_bias(trajectory)


# ============================================================
# ALIGNMENT FUNCTIONS (plan extraction + validation)
# ============================================================

ALIGNMENT_THRESHOLD = 0.5

_ACTION_TOKENS = frozenset([
    '=', 'copy(', 'if ', 'for ', 'append(', 'return ', 'raise ',
    '.pop(', '.get(', '.update(', '.insert(', 'del ', 'import ',
    'try:', 'except', 'with ', '.clear(', '.add(',
])


def _extract_plan(raw_output):
    """Extract structured plan from model output."""
    plan_match = re.search(r'PLAN:\s*\n((?:\d+\..*\n?)+)', raw_output)
    invariant_match = re.search(r'INVARIANT:\s*(.*)', raw_output)
    if not plan_match:
        return None
    steps = re.findall(r'\d+\.\s*(.*)', plan_match.group(1))
    if not steps:
        return None
    invariant = invariant_match.group(1).strip() if invariant_match else None
    return {"steps": steps, "invariant": invariant}


def _extract_action_keywords(step_text):
    """Extract semantic action keywords from a plan step."""
    cleaned = re.sub(r'\b(in|the|a|an|to|of|for|and|or|by|with|from)\b', '', step_text.lower())
    words = re.findall(r'[a-zA-Z_]\w{3,}', cleaned)
    generic = {'should', 'must', 'need', 'change', 'update', 'make', 'ensure',
               'function', 'method', 'variable', 'code', 'line', 'file'}
    return [w for w in words if w not in generic]


def _step_implemented(step_text, code):
    """Check if a plan step is reflected in code. Requires keyword + action token."""
    keywords = _extract_action_keywords(step_text)
    if not keywords:
        return True
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3
    has_action = any(tok in code for tok in _ACTION_TOKENS)
    return keyword_covered and has_action


def _compute_step_coverage(plan, code):
    """Compute fraction of plan steps reflected in code."""
    if not plan or not plan.get("steps"):
        return 0.0, []
    per_step = []
    for step in plan["steps"]:
        impl = _step_implemented(step, code)
        per_step.append({"step": step[:80], "implemented": impl})
    implemented = sum(1 for s in per_step if s["implemented"])
    coverage = implemented / len(plan["steps"])
    return round(coverage, 3), per_step


def _plan_matches_failure(plan, error_obj, classification):
    """Does the plan address the actual failure type?"""
    if not plan or not plan.get("invariant"):
        return None
    invariant_lower = plan["invariant"].lower()
    error_category = error_obj.get("category", "")
    if error_category in ("syntax", "runtime", "load"):
        if error_category == "syntax" and "syntax" not in invariant_lower:
            return False
        if error_category == "runtime":
            err_type = (error_obj.get("message", "").split(":")[0] or "").lower()
            if err_type and err_type not in invariant_lower:
                return False
    if classification and classification.get("failure_type_final") != "UNKNOWN":
        classifier_words = classification["failure_type_final"].lower().replace("_", " ").split()
        overlap = any(w in invariant_lower for w in classifier_words if len(w) > 3)
        if not overlap:
            steps_text = " ".join(plan.get("steps", [])).lower()
            overlap = any(w in steps_text for w in classifier_words if len(w) > 3)
        if not overlap:
            return False
    return True


def _compute_alignment(plan, code, error_obj, classification):
    """Compute all alignment fields from plan + code."""
    if plan is None:
        return None
    step_coverage, per_step = _compute_step_coverage(plan, code)
    plan_matches = _plan_matches_failure(plan, error_obj, classification)
    alignment_success = (plan_matches is True) and (step_coverage >= ALIGNMENT_THRESHOLD)
    return {
        "step_coverage": step_coverage,
        "per_step": per_step,
        "plan_matches_failure": plan_matches,
        "alignment_success": alignment_success,
    }


def _classify_failure_trajectory(failure_sequence):
    """ANALYSIS ONLY — classify failure type sequence pattern."""
    types = [t for t in failure_sequence if t is not None]
    if len(types) <= 1:
        return "single"
    if len(set(types)) == 1:
        return "stable"
    if len(types) >= 3 and types[-1] == types[-2]:
        return "converging"
    for i in range(1, len(types)):
        if types[i] == types[i - 1]:
            break
    else:
        return "oscillating"
    return "mixed"


# ============================================================
# CLASSIFIERS (post-hoc)
# ============================================================

def _classify_outcome(trajectory):
    """What happened: convergence dynamics."""
    n = len(trajectory)
    if n == 1 and trajectory[0]["pass"]:
        return "single_shot"
    if trajectory[-1]["pass"] and n <= 3:
        return "fast_convergence"
    if trajectory[-1]["pass"] and n > 3:
        return "slow_convergence"
    return "no_convergence"


def _classify_trajectory_type(trajectory):
    """Classify the score trajectory shape."""
    scores = [e["score"] for e in trajectory]
    n = len(scores)

    if n == 1:
        return "single_shot"

    improving = all(scores[i] >= scores[i - 1] for i in range(1, n))
    if improving and scores[-1] > scores[0] and trajectory[-1]["pass"]:
        return "monotonic_improvement"

    # Check oscillation BEFORE partial_stall (oscillation is more specific)
    direction_changes = 0
    for i in range(2, n):
        prev_dir = scores[i - 1] - scores[i - 2]
        curr_dir = scores[i] - scores[i - 1]
        if prev_dir * curr_dir < 0:
            direction_changes += 1
    if direction_changes >= 1:
        return "oscillating"

    ever_improved = any(scores[i] > scores[i - 1] for i in range(1, n))
    if ever_improved and not trajectory[-1]["pass"]:
        return "partial_stall"

    if len(set(scores)) == 1 and not trajectory[-1]["pass"]:
        return "flat_failure"

    return "other"


def _classify_regime(trajectory):
    """Why it happened: mechanism analysis.

    Returns (regime, mechanism_signals).
    """
    if not trajectory:
        return "unknown", {}

    n = len(trajectory)
    converged = trajectory[-1]["pass"]

    diffs = [e["diff"] for e in trajectory[1:] if e.get("diff")]
    avg_diff = sum(d["chars_changed"] for d in diffs) / len(diffs) if diffs else 0
    diff_small = avg_diff < 100

    r_signals = [e.get("reasoning_signals", {}).get("estimated_valid")
                 for e in trajectory if e.get("reasoning_signals")]
    r_valid = [s for s in r_signals if s is not None]
    reasoning_consistent = all(r_valid) if r_valid else False

    # Only valid critiques count
    critiques = [e["critique"] for e in trajectory
                 if e.get("critique") and e["critique"].get("_valid")]
    if len(critiques) >= 2:
        root_causes = [c.get("root_cause", "") for c in critiques]
        pairwise = [_keyword_overlap(root_causes[i], root_causes[i + 1])
                    for i in range(len(root_causes) - 1)]
        critique_consistent = sum(pairwise) / len(pairwise) > 0.3
    else:
        critique_consistent = True

    mechanism_signals = {
        "reasoning_consistent": reasoning_consistent,
        "critique_consistent": critique_consistent,
        "diff_small": diff_small,
        "avg_diff_size": round(avg_diff, 1),
    }

    if n == 1 and converged:
        regime = "heuristic"
    elif reasoning_consistent and diff_small:
        regime = "REI"
    elif not reasoning_consistent and not diff_small:
        regime = "CSF"
    elif not critique_consistent:
        regime = "CSF"
    else:
        regime = "mixed"

    return regime, mechanism_signals


# ============================================================
# METRICS
# ============================================================

def _compute_metrics(trajectory):
    """Compute retry metrics from trajectory."""
    n = len(trajectory)
    diffs = [e["diff"] for e in trajectory[1:] if e.get("diff")]
    scores = [e["score"] for e in trajectory]
    error_types = [e["error"]["category"] for e in trajectory if e.get("error")]
    converged = trajectory[-1]["pass"]

    avg_diff = sum(d["chars_changed"] for d in diffs) / len(diffs) if diffs else 0
    avg_disp = sum(d["edit_dispersion"] for d in diffs) / len(diffs) if diffs else 1.0
    convergence_slope = (scores[-1] - scores[0]) / max(n - 1, 1)

    if error_types:
        counts = Counter(error_types)
        total_c = sum(counts.values())
        probs = [c / total_c for c in counts.values()]
        error_entropy = -sum(p * math.log2(p) for p in probs if p > 0)
    else:
        error_entropy = 0.0

    return {
        "num_retries": n - 1,
        "total_attempts": n,
        "avg_diff_size": round(avg_diff, 1),
        "avg_edit_dispersion": round(avg_disp, 3),
        "convergence_slope": round(convergence_slope, 3),
        "retry_efficiency": round(1.0 / n, 3) if converged else 0.0,
        "error_entropy": round(error_entropy, 3),
        "score_trajectory": scores,
        "stagnated": (n > 1 and bool(diffs) and
                      _is_stagnated(diffs[-1], scores[-1],
                                    scores[-2] if n > 1 else 0)),
    }


def _compute_critique_accuracy(trajectory):
    """Does critique_k's root_cause align with actual changes in code_(k+1)?

    Filters generic words. Only counts valid critiques.
    """
    hits = 0
    total = 0
    for i in range(len(trajectory) - 1):
        critique = trajectory[i].get("critique")
        if not critique or not critique.get("_valid"):
            continue
        next_diff = trajectory[i + 1].get("diff")
        if not next_diff or not next_diff.get("diff_text"):
            continue
        total += 1

        root_cause = critique.get("root_cause", "")
        cause_words = {w.lower() for w in re.findall(r'[a-zA-Z_]\w{3,}', root_cause)
                       if w.lower() not in _GENERIC_WORDS}

        diff_text = next_diff["diff_text"]
        diff_words = {w.lower() for w in re.findall(r'[a-zA-Z_]\w{3,}', diff_text)
                      if w.lower() not in _GENERIC_WORDS}

        if cause_words & diff_words:
            hits += 1

    return round(hits / total, 3) if total > 0 else None


# ============================================================
# LLM-TOUCHING FUNCTIONS
# ============================================================

def _call_critique(model, code_k, error_obj, ev):
    """Separate model call for structured failure diagnosis.

    Returns dict with _valid=True on success, _valid=False on parse failure.
    """
    test_output = _format_test_output(ev)
    prompt = f"""You are analyzing a code fix attempt that FAILED its tests.

=== Code Under Test ===
```python
{code_k}
```

=== Test Results ===
{test_output}

Respond with ONLY this JSON (no other text):
{{
  "failure_type": "syntax | runtime | logic_error | spec_mismatch",
  "root_cause": "one sentence describing the root cause",
  "invariant_violated": "which invariant failed",
  "confidence": 0.8,
  "is_reasoning_error": false
}}"""
    try:
        raw = call_model(prompt, model=model, raw=True)
        result = json.loads(raw)
        # Type-coerce is_reasoning_error
        ire = result.get("is_reasoning_error")
        if isinstance(ire, str):
            result["is_reasoning_error"] = ire.lower() in ("true", "yes", "1")
        result["_valid"] = True
        return result
    except Exception:
        return {
            "failure_type": "unknown", "root_cause": "unparseable",
            "invariant_violated": "unknown", "confidence": 0.0,
            "is_reasoning_error": None, "_valid": False,
        }


def _elicit_contract(case, model):
    """CGE lite: elicit intent before coding. Logged, used as context on retry."""
    prompt = f"""Before fixing this bug, state your intent.

{case["task"]}

Respond with ONLY this JSON:
{{
  "bug_identified": "what is wrong",
  "fix_approach": "how you will fix it",
  "invariants_to_preserve": ["list of invariants"]
}}"""
    try:
        raw = call_model(prompt, model=model, raw=True)
        return json.loads(raw)
    except Exception:
        return None


# ============================================================
# PROMPT BUILDERS
# ============================================================

_ALIGNMENT_EXTRA = """

IMPORTANT: In the "plan" field of your JSON response, list each change as a separate step.
Each step should specify which function you are changing and what you are changing.
Example: ["In create_config: return DEFAULTS.copy() instead of DEFAULTS", "In reset: clear cache"]"""


def _build_initial_prompt(case, use_alignment=False):
    """Baseline prompt. Adds alignment emphasis if alignment mode."""
    code_files = case["code_files_contents"]
    base = build_base_prompt(case["task"], code_files)
    if use_alignment:
        return base + _ALIGNMENT_EXTRA
    return base


def _build_retry_prompt(case, original_code, prev_code, test_output, critique, contract,
                        adaptive_hint=None, trajectory_context=None,
                        use_alignment=False):
    """Retry prompt with test feedback, critique, optional contract/hints."""
    parts = [case["task"]]
    parts.append(f"\n=== Original Code ===\n{original_code}")
    parts.append(f"\n=== Your Previous Attempt ===\n```python\n{prev_code}\n```")
    parts.append(f"\n=== Test Results (FAILED) ===\n{test_output}")
    if critique:
        parts.append(f"\n=== Diagnosis ===\n{json.dumps(_clean_critique_for_log(critique), indent=2)}")
    if contract:
        parts.append(f"\n=== Your Intended Fix ===\n{json.dumps(contract, indent=2)}")
    if adaptive_hint:
        parts.append(f"\n=== Hint ===\n{adaptive_hint}")
    if trajectory_context:
        parts.append(f"\n=== Trajectory Feedback ===\n{trajectory_context}")
    parts.append("\nFix the failing tests with minimal changes to your previous attempt.")
    parts.append("Return the complete updated code.")
    if use_alignment:
        parts.append(_ALIGNMENT_EXTRA)
    return "\n".join(parts)
    # call_model() appends _JSON_OUTPUT_INSTRUCTION automatically


# ============================================================
# LOGGING
# ============================================================

def _write_iteration_log(case, model, k, max_iterations, condition,
                         prompt, raw, parsed, ev, entry):
    """Write one iteration via the active RunLogger."""
    from execution import get_run_logger, get_model_config as _gmc

    reasoning_text = parsed.get("reasoning") or ""
    code_text = parsed.get("code") or ""

    logger = get_run_logger()

    record = {
        "run_id": logger.run_id,
        "case_id": case["id"], "condition": condition, "model": model,
        "iteration": k, "max_iterations": max_iterations,
        "model_config": _gmc(),
        "prompt_length": len(prompt),
        "raw_response_length": len(raw),
        "parsed": {
            "reasoning": reasoning_text[:200] if isinstance(reasoning_text, str) else "",
            "code_length": len(code_text) if isinstance(code_text, str) else 0,
            "parse_error": parsed.get("parse_error"),
        },
        "execution": ev.get("execution", {}),
        "evaluation": {
            "pass": ev["pass"], "score": ev["score"],
            "reasoning_valid": ev.get("identified_correct_issue", False),
            "alignment": ev.get("alignment", {}),
        },
    }

    prompt_record = {
        "run_id": logger.run_id,
        "case_id": case["id"], "condition": condition, "model": model,
        "iteration": k, "prompt": prompt,
    }

    response_record = {
        "run_id": logger.run_id,
        "case_id": case["id"], "condition": condition, "model": model,
        "iteration": k, "raw_response": raw,
    }

    # Model mismatch check — same as RunLogger.write but for the manual path
    if model != logger.model:
        raise RuntimeError(
            f"LOG MODEL MISMATCH in retry harness: logger model='{logger.model}', "
            f"write model='{model}'. Cross-run contamination detected."
        )

    for path, data in [(logger.log_path, record),
                        (logger.prompts_path, prompt_record),
                        (logger.responses_path, response_record)]:
        logger.writes_attempted += 1
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, default=str) + "\n")
        except OSError as e:
            logger.writes_failed += 1
            _log.error("LOG WRITE FAILED for %s/%s to %s: %s",
                       case["id"], condition, path, e)


def _write_retry_summary(case, model, condition, summary):
    """Write summary record via the active RunLogger."""
    from execution import get_run_logger

    logger = get_run_logger()
    logger.write_summary(summary)


# ============================================================
# MAIN LOOP
# ============================================================

def run_retry_harness(case, model, max_iterations=5, use_contract=False,
                      use_adaptive=False, use_alignment=False,
                      use_llm_eval=False, eval_model=None):
    """Run retry harness. Returns (case_id, condition, ev).

    A scientific measurement instrument for reasoning-execution dynamics.

    Args:
        eval_model: model to use for LEG evaluator calls. If None, uses `model`.
                    Set to a different model to avoid self-evaluation bias.

    Control signals (in-loop): consecutive_same_failure, similarity, score_improving
    Analysis signals (post-hoc): trajectory_dynamics, transition_entropy, LEG metrics
    """
    if use_alignment:
        condition = "retry_alignment"
    elif use_adaptive:
        condition = "retry_adaptive"
    elif use_contract:
        condition = "retry_with_contract"
    else:
        condition = "retry_no_contract"
    original_code = _format_code_files(case["code_files_contents"])
    trajectory = []
    prev_code = None
    prev_score = 0.0
    model_call_count = 0

    # Contract (elicited upfront, used only on k>0)
    contract = None
    if use_contract:
        contract = _elicit_contract(case, model)
        model_call_count += 1

    total_start = time.monotonic()
    critique = None
    test_output = ""
    ev = None
    consecutive_same_failure = 0
    consecutive_high_sim = 0
    score_improving = False
    adaptive_hint = None
    trajectory_context = None

    for k in range(max_iterations):
        # Wallclock safety
        elapsed = time.monotonic() - total_start
        if elapsed > MAX_TOTAL_SECONDS:
            _log.warning("TIMEOUT for %s after %.1fs at iteration %d",
                         case["id"], elapsed, k)
            break

        # --- Generate ---
        if k == 0:
            prompt = _build_initial_prompt(case, use_alignment=use_alignment)
        else:
            prompt = _build_retry_prompt(
                case, original_code, prev_code, test_output, critique,
                contract,  # None if use_contract=False
                adaptive_hint=adaptive_hint,
                trajectory_context=trajectory_context,
                use_alignment=use_alignment,
            )

        iter_start = time.monotonic()
        raw = call_model(prompt, model=model)
        model_call_count += 1
        iter_elapsed = time.monotonic() - iter_start
        if iter_elapsed > MAX_ITERATION_SECONDS:
            _log.warning("SLOW ITERATION for %s: %.1fs at iteration %d",
                         case["id"], iter_elapsed, k)

        # --- Evaluate through canonical pipeline ---
        from execution import evaluate_case, _propagate_observability
        parsed_result, ev = evaluate_case(case, raw)
        _propagate_observability(parsed_result, ev)

        code_k = parsed_result.get("code", "")
        reasoning_k = parsed_result.get("reasoning", "")
        valid_schema = parsed_result.get("response_format") in ("json_direct", "json_lenient")

        # Extract plan from raw JSON (metadata, not needed for evaluation)
        plan_steps = []
        try:
            import json as _json
            raw_json = _json.loads(raw) if raw.strip().startswith("{") else {}
            if isinstance(raw_json, dict) and isinstance(raw_json.get("plan"), list):
                plan_steps = raw_json["plan"]
        except (ValueError, TypeError):
            pass

        # --- Structured error ---
        error_obj = _build_error_object(ev)

        # --- Diff ---
        diff_k = _compute_diff(prev_code, code_k) if prev_code else None

        # --- Critique (only on failure, not on last iteration) ---
        critique = None
        if not ev["pass"] and k < max_iterations - 1:
            critique = _call_critique(model, code_k, error_obj, ev)
            model_call_count += 1

        # --- Classification (from failure_classifier, no ground truth) ---
        classification = None
        if not ev["pass"]:
            from failure_classifier import classify_failure
            classification = classify_failure(error_obj, critique)

        # --- Reasoning signals ---
        reasoning_signals = _estimate_reasoning_validity(
            critique, reasoning_k, case, raw, trajectory, k
        )

        # --- Predicted failure mode ---
        predicted_failure_mode = _infer_failure_mode(error_obj, diff_k, critique)

        # --- Attempt similarity (SequenceMatcher) ---
        attempt_similarity = None
        if prev_code and code_k:
            attempt_similarity = round(SequenceMatcher(None, prev_code, code_k).ratio(), 3)

        # --- Latent correctness signal ---
        latent_signal = _detect_latent_signal(reasoning_k, ev["pass"])

        # --- Control signals (incremental, O(1) per iteration) ---
        if k > 0 and not ev["pass"]:
            current_type = classification["failure_type_final"] if classification else None
            prev_type = trajectory[-1].get("failure_type") if trajectory else None

            # Control 1: Same failure repeating (with error message fallback)
            types_match = (current_type and current_type == prev_type
                           and current_type != "UNKNOWN")
            if not types_match and (not current_type or current_type == "UNKNOWN"):
                prev_msg = trajectory[-1].get("error", {}).get("message", "")
                curr_msg = error_obj.get("message", "")
                if prev_msg and curr_msg:
                    types_match = SequenceMatcher(None, prev_msg, curr_msg).ratio() > 0.8

            if types_match:
                consecutive_same_failure += 1
            else:
                consecutive_same_failure = 0

            # Control 2: High code similarity
            if attempt_similarity and attempt_similarity > SIMILARITY_THRESHOLD:
                consecutive_high_sim += 1
            else:
                consecutive_high_sim = 0

            # Control 3: Score improving (epsilon-tolerant)
            score_improving = ev["score"] > prev_score + SCORE_EPSILON

        # --- Adaptive hint (confidence-gated, CONTROL) ---
        adaptive_hint = None
        hint_used_type = None
        trajectory_context = None
        if use_adaptive and not ev["pass"] and classification:
            if classification["classifier_confidence"] >= 0.5:
                hint_used_type = classification["failure_type_final"]
                adaptive_hint = ADAPTIVE_HINTS.get(hint_used_type, ADAPTIVE_HINTS["UNKNOWN"])
            else:
                hint_used_type = "DEFAULT"
                adaptive_hint = ADAPTIVE_HINTS["UNKNOWN"]

            # Trajectory-aware escalation (CONTROL signals only)
            if k >= 1:
                if consecutive_same_failure >= PERSISTENCE_ESCALATION_COUNT:
                    trajectory_context = (
                        f"The same failure ({current_type}) has persisted for "
                        f"{consecutive_same_failure + 1} attempts. "
                        f"Your previous approaches are not working. "
                        f"Try a fundamentally different strategy.")
                elif consecutive_high_sim >= PERSISTENCE_ESCALATION_COUNT:
                    trajectory_context = (
                        "Your last attempts produced nearly identical code. "
                        "You must make a meaningfully different change. "
                        "Reconsider your assumptions about the root cause.")
                elif k >= 2 and not score_improving and ev["score"] <= trajectory[-2].get("score", 0) + SCORE_EPSILON:
                    trajectory_context = (
                        "Your score has not improved in the last 2 attempts. "
                        "Consider a broader approach to the problem.")

        # --- Trajectory entry ---
        entry = {
            "attempt": k,
            "code": code_k,
            "reasoning": reasoning_k,
            "error": error_obj,
            "critique": _clean_critique_for_log(critique),
            "critique_valid": critique["_valid"] if critique else None,
            "diff": diff_k,
            "pass": ev["pass"],
            "score": ev["score"],
            "execution_success": ev["pass"],
            "reasoning_signals": reasoning_signals,
            "predicted_failure_mode": predicted_failure_mode,
            # Trajectory-aware fields
            "code_hash": hashlib.md5(code_k.encode()).hexdigest()[:12] if code_k else None,
            "failure_type": classification["failure_type_final"] if classification else None,
            "similarity_to_previous": attempt_similarity,
            "attempt_progress": round(k / max_iterations, 3),
            "classification": classification,
            "intervention": {
                "type": hint_used_type,
                "confidence": classification["classifier_confidence"] if classification else None,
                "applied": adaptive_hint is not None and hint_used_type != "DEFAULT",
                "hint_text": adaptive_hint,
                "trajectory_context": trajectory_context,
            } if use_adaptive and not ev["pass"] else None,
            "hint_used_type": hint_used_type,
            "latent_signal": latent_signal,
            # Schema compliance
            "valid_schema": valid_schema,
            "plan_steps": plan_steps if valid_schema else [],
            # Alignment fields (alignment condition only)
            "alignment_step_coverage": None,
            "alignment_success": None,
            "alignment_plan_matches": None,
            "alignment_per_step": None,
        }

        # --- Alignment computation (uses structured plan from JSON) ---
        if use_alignment:
            plan = None
            if valid_schema and plan_steps:
                # Plan comes from structured JSON output — no regex needed
                plan = {"steps": plan_steps, "invariant": None}
            elif not valid_schema:
                # Schema failed — try legacy regex extraction as fallback
                plan = _extract_plan(raw) or _extract_plan(reasoning_k)
            if plan and code_k:
                alignment = _compute_alignment(plan, code_k, error_obj, classification)
                if alignment:
                    entry["alignment_step_coverage"] = alignment["step_coverage"]
                    entry["alignment_success"] = alignment["alignment_success"]
                    entry["alignment_plan_matches"] = alignment["plan_matches_failure"]
                    entry["alignment_per_step"] = alignment["per_step"]

                    # Structured alignment feedback for retry prompt
                    if not ev["pass"] and not alignment["alignment_success"] and k < max_iterations - 1:
                        missing = [s["step"] for s in alignment["per_step"] if not s["implemented"]]
                        if missing:
                            trajectory_context = (
                                f"Your plan has {len(alignment['per_step'])} steps, "
                                f"but only {alignment['step_coverage']:.0%} are implemented.\n\n"
                                f"Missing steps:\n" +
                                "\n".join(f"- {s}" for s in missing[:3]) +
                                "\n\nImplement ALL steps in your code."
                            )

        trajectory.append(entry)

        # --- Log iteration ---
        _write_iteration_log(case, model, k, max_iterations, condition,
                             prompt, raw, parsed_result, ev, entry)

        # --- ANALYSIS logging (observations, NOT stop conditions) ---
        if k >= 2:
            dynamics = _classify_trajectory_dynamics(trajectory)
            if dynamics["oscillation"]:
                _log.info("OSCILLATION detected for %s at iteration %d", case["id"], k)
            if dynamics["divergence"]:
                _log.info("DIVERGENCE detected for %s at iteration %d", case["id"], k)

        # --- Stop conditions ---
        if ev["pass"]:
            break

        # Stagnation: similarity-based (primary)
        if k > 0 and consecutive_high_sim >= 3:
            _log.info("STAGNATION (similarity) for %s at iteration %d", case["id"], k)
            break

        # Stagnation: diff-based (secondary, kept for backward compat)
        if k > 0 and diff_k and _is_stagnated(diff_k, ev["score"], prev_score):
            _log.info("STAGNATION (diff) for %s at iteration %d", case["id"], k)
            break

        prev_code = code_k
        prev_score = ev["score"]
        test_output = _format_test_output(ev)

    # --- Handle edge case: loop never ran (timeout at k=0) ---
    if ev is None:
        ev = {
            "pass": False, "score": 0.0,
            "reasons": ["timeout_before_first_iteration"],
            "execution": {"status": "error", "ran": False},
        }

    # --- LEG EVALUATION (post-hoc, gated by use_llm_eval) ---
    if use_llm_eval and trajectory:
        from leg_evaluator import evaluate_reasoning, compute_leg_true, compute_reasoning_matches_truth
        for entry in trajectory:
            if not entry["pass"] and entry.get("reasoning"):
                ft = entry.get("classifier_failure_type") or (
                    entry.get("classification", {}) or {}).get("failure_type_final")

                if not entry.get("code") or not entry["code"].strip():
                    _log.warning(
                        "LEG EVAL with EMPTY CODE for %s iter %d — "
                        "evaluator will judge reasoning without seeing code",
                        case["id"], entry.get("attempt", -1)
                    )

                blind = evaluate_reasoning(
                    model, entry["reasoning"], entry["code"],
                    entry["error"], blind=True, eval_model=eval_model)
                entry["llm_eval_blind_verdict"] = blind["verdict"]
                entry["llm_eval_blind_type"] = blind["inferred_type"]
                entry["llm_eval_blind_raw"] = blind["raw"]
                entry["llm_eval_blind_parse_error"] = blind["parse_error"]

                conditioned = evaluate_reasoning(
                    model, entry["reasoning"], entry["code"],
                    entry["error"], classifier_type=ft, blind=False,
                    eval_model=eval_model)
                entry["llm_eval_conditioned_verdict"] = conditioned["verdict"]
                entry["llm_eval_conditioned_type"] = conditioned["inferred_type"]
                entry["llm_eval_conditioned_raw"] = conditioned["raw"]
                entry["llm_eval_conditioned_parse_error"] = conditioned["parse_error"]

                model_call_count += 2

                # Compute LEG fields
                entry["classifier_failure_type"] = ft
                entry["reasoning_matches_truth"] = compute_reasoning_matches_truth(entry)
                entry["leg_true"] = compute_leg_true(entry)
            else:
                entry["llm_eval_blind_verdict"] = None
                entry["llm_eval_blind_type"] = None
                entry["llm_eval_blind_raw"] = None
                entry["llm_eval_blind_parse_error"] = None
                entry["llm_eval_conditioned_verdict"] = None
                entry["llm_eval_conditioned_type"] = None
                entry["llm_eval_conditioned_raw"] = None
                entry["llm_eval_conditioned_parse_error"] = None
                entry["reasoning_matches_truth"] = False
                entry["leg_true"] = False

            # LEG subtypes (alignment condition only)
            if entry.get("alignment_success") is not None:
                entry["leg_coupling"] = entry["leg_true"] and not entry["alignment_success"]
                entry["leg_execution"] = entry["leg_true"] and entry["alignment_success"]
            else:
                entry["leg_coupling"] = None
                entry["leg_execution"] = None

    # --- Post-hoc ANALYSIS (computed after loop, not used for control) ---
    regime, mechanism_signals = _classify_regime(trajectory) if trajectory else ("unknown", {})
    outcome = _classify_outcome(trajectory) if trajectory else "no_convergence"
    traj_type = _classify_trajectory_type(trajectory) if trajectory else "other"
    metrics = _compute_metrics(trajectory) if trajectory else {}
    critique_acc = _compute_critique_accuracy(trajectory)

    last_predicted = trajectory[-1]["predicted_failure_mode"] if trajectory else "unknown"
    iterations_executed = len(trajectory)

    # Raw signal sequences (always logged for post-hoc recomputation)
    score_seq = [e["score"] for e in trajectory]
    ft_seq = [e.get("failure_type") for e in trajectory]
    sim_seq = [e.get("similarity_to_previous") for e in trajectory]
    error_msgs = [e.get("error", {}).get("message", "") for e in trajectory]

    # Derived analysis signals
    failure_seq = [t for t in ft_seq if t is not None]
    transitions = _compute_transitions(failure_seq)
    dynamics = _classify_trajectory_dynamics(trajectory) if len(trajectory) > 1 else {
        "pattern": "single_shot", "oscillation": False, "divergence": False,
        "stagnation": False, "convergence": False, "score_reversals": 0,
        "type_changes": 0, "max_consecutive_similar": 0}

    # Trajectory metrics (ANALYSIS only)
    metrics["transition_entropy"] = _compute_transition_entropy(transitions)
    metrics["trajectory_stability"] = _trajectory_stability_score(failure_seq)
    metrics["oscillation_rate"] = _oscillation_rate(trajectory)
    metrics["local_fix_ratio"] = _local_vs_global_ratio(trajectory)
    metrics["convergence_depth"] = _compute_convergence_depth(trajectory)

    # First-pass attribution
    first_pass_success = trajectory[0]["pass"] if trajectory else False
    recovered = (not first_pass_success) and ev["pass"]

    # Retry effectiveness
    initial_score = trajectory[0]["score"] if trajectory else 0
    final_score = trajectory[-1]["score"] if trajectory else 0

    # Classifier coverage
    failed_entries = [e for e in trajectory if not e["pass"] and e.get("classification")]
    classifier_coverage = {}
    if failed_entries:
        confident = sum(1 for e in failed_entries if e["classification"]["classifier_confidence"] >= 0.5)
        applied = sum(1 for e in trajectory if e.get("intervention", {}) and e["intervention"] and e["intervention"].get("applied"))
        types = Counter(e["classification"]["failure_type_final"] for e in failed_entries)
        classifier_coverage = {
            "total_classifications": len(failed_entries),
            "confident_predictions": confident,
            "confident_prediction_rate": round(confident / len(failed_entries), 3),
            "adaptive_applied_count": applied,
            "adaptive_applied_rate": round(applied / len(failed_entries), 3) if failed_entries else 0,
            "type_distribution": dict(types),
        }

    # Latent execution gap
    latent_entries = [e for e in trajectory if e.get("latent_signal", {}).get("correct_pattern_in_reasoning")]
    latent_gap = {
        "latent_but_failed": sum(1 for e in latent_entries if not e["pass"]),
        "latent_and_succeeded": sum(1 for e in latent_entries if e["pass"]),
    }

    # Attempt diversity
    sims = [e.get("similarity_to_previous") for e in trajectory[1:]
            if e.get("similarity_to_previous") is not None]
    attempt_diversity = round(1.0 - sum(sims) / len(sims), 3) if sims else 0.0

    summary = {
        "case_id": case["id"],
        "condition": condition,
        "model": model,
        "iteration": "summary",
        "final_status": "success" if ev["pass"] else "fail",
        "ground_truth_failure_mode": case.get("failure_mode"),
        "predicted_failure_mode": last_predicted,
        "outcome_type": outcome,
        "failure_regime": regime,
        "mechanism_signals": mechanism_signals,
        "trajectory_type": traj_type,
        # Raw signal sequences
        "status_sequence": ["pass" if e["pass"] else "fail" for e in trajectory],
        "score_sequence": score_seq,
        "failure_type_sequence": ft_seq,
        "similarity_sequence": sim_seq,
        "num_type_changes": sum(1 for i in range(1, len(failure_seq)) if failure_seq[i] != failure_seq[i - 1]) if len(failure_seq) > 1 else 0,
        "num_score_reversals": _count_reversals(score_seq),
        "consecutive_same_failure_lengths": _run_lengths(ft_seq),
        # Derived analysis signals
        "error_trajectory": [e["error"]["category"] for e in trajectory],
        "error_trajectory_detailed": [
            {"category": e["error"]["category"],
             "message": e["error"]["message"][:200],
             "invariant": (e["critique"].get("invariant_violated")
                           if e.get("critique") and e.get("critique_valid") else None)}
            for e in trajectory
        ],
        "failure_sequence": failure_seq,
        "failure_transitions": transitions,
        "trajectory_dynamics": dynamics,
        "trajectory_failure_pattern": _classify_failure_trajectory(failure_seq),
        "failure_persistence": _compute_failure_persistence(ft_seq, error_msgs),
        # Attribution
        "first_pass_success": first_pass_success,
        "recovered_on_retry": recovered,
        "retry_gain": recovered,
        "retry_effectiveness": {
            "improved": final_score > initial_score,
            "stagnant": final_score == initial_score and len(trajectory) > 1,
            "regressed": final_score < initial_score,
        },
        # Classifier
        "classifier_coverage": classifier_coverage,
        # Latent
        "latent_execution_gap": latent_gap,
        "attempt_diversity": attempt_diversity,
        # LEG metrics (populated if use_llm_eval)
        "leg_rate_true": _leg_rate(trajectory, "leg_true") if use_llm_eval else None,
        "leg_rate_keyword": _leg_rate(trajectory, "leg_keyword_only"),
        "leg_resolution_rate_true": _leg_resolution(trajectory, "leg_true") if use_llm_eval else None,
        "leg_coupling_rate": _leg_rate(trajectory, "leg_coupling") if use_llm_eval and use_alignment else None,
        "leg_execution_rate": _leg_rate(trajectory, "leg_execution") if use_llm_eval and use_alignment else None,
        "evaluator_parse_failure_rate_blind": _eval_parse_rate(trajectory, "llm_eval_blind_parse_error") if use_llm_eval else None,
        "evaluator_parse_failure_rate_conditioned": _eval_parse_rate(trajectory, "llm_eval_conditioned_parse_error") if use_llm_eval else None,
        "evaluator_bias": _compute_eval_bias(trajectory) if use_llm_eval else None,
        # Schema compliance
        "schema_compliance_rate": round(
            sum(1 for e in trajectory if e.get("valid_schema")) / len(trajectory), 3
        ) if trajectory else 0.0,
        # Standard
        "contract_used": use_contract,
        "contract": contract,
        "metrics": metrics,
        "critique_accuracy": critique_acc,
        "converged": ev["pass"],
        "iterations_to_success": (
            next((i for i, e in enumerate(trajectory) if e["pass"]), None)
            if ev["pass"] else None
        ),
        "total_iterations_executed": iterations_executed,
        "total_model_calls": model_call_count,
        "trajectory": [{k2: v for k2, v in e.items() if k2 != "code"}
                       for e in trajectory],
    }

    _write_retry_summary(case, model, condition, summary)

    ev.update(
        condition=condition,
        operator_used="RETRY_HARNESS",
        num_attempts=iterations_executed,
        final_pass=ev["pass"],
        retry_summary=summary,
    )
    # alignment is already computed correctly by evaluate_output inside evaluate_case.
    # Do NOT recompute — the previous version used wrong arguments.

    # Write final iteration to run.jsonl and events.jsonl (V10 fix)
    from execution import write_log, _emit_metrics_event
    if trajectory:
        # Use last iteration's data for logging
        last_prompt = prompt  # loop variable from last iteration
        last_raw = raw        # loop variable from last iteration
        write_log(case["id"], condition, model, last_prompt, last_raw, parsed_result, ev)
    _emit_metrics_event(case, model, condition, ev,
                        elapsed_seconds=round(time.monotonic() - total_start, 2))

    return case["id"], condition, ev
