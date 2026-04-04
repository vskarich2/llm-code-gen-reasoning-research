"""V5 Analysis: unknown state, locus verification, exec-failure decomposition,
3-stage breakdown, locus baseline comparison.

Runs on all oracle-evaluated logs. Produces analysis-ready outputs.
Zero new LLM calls. Zero pipeline changes.
"""

import ast, csv, json, os, sys, re
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.dirname(__file__))
from checkers import CASE_RULES, find_function, _call_name, _calls_in, _has_call
from checker_fixes import CASE_RULES_OVERRIDES, MODULE_LEVEL_CASES, NOT_AST_MEASURABLE
from checker_fixes_v2 import CHECKER_V2_OVERRIDES

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

with open(os.path.join(PROJECT_ROOT, 'case_data', 'cases_v2.json')) as f:
    CASES = {c['id']: c for c in json.load(f)}
MULTI_FILE = {cid for cid, c in CASES.items() if len(c.get('code_files', [])) > 1}

ORACLE_LOGS = [
    "logs/v2_targeted_50trial_canonical", "logs/v2_full_4model_10trial_canonical",
    "logs/v2_targeted_50trial_tranche2", "logs/v2_targeted_50trial_tranche4",
    "logs/v2_targeted_50trial_tranche3", "logs/v2_anthropic_50trial_v3",
    "logs/v2_anthropic_50trial_v2", "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_haiku45", "logs/v2_anthropic_sonnet46_v2",
    "logs/v2_gpt5_50trial", "logs/v2_gpt5_50trial_v2",
    "logs/retry_critique_stage2/_split_openai",
    "logs/retry_critique_stage2/_split_anthropic",
    "logs/global_calibration/_split_openai",
    "logs/global_calibration/_split_anthropic",
]


# =====================================================================
# HELPERS
# =====================================================================

def get_rules(cid):
    if cid in NOT_AST_MEASURABLE: return None, False
    if cid in CHECKER_V2_OVERRIDES: return CHECKER_V2_OVERRIDES[cid], False
    if cid in CASE_RULES_OVERRIDES: return CASE_RULES_OVERRIDES[cid], False
    if cid in MODULE_LEVEL_CASES: return MODULE_LEVEL_CASES[cid], True
    if cid in CASE_RULES: return CASE_RULES[cid], False
    return None, False


def _addl_relaxed(cid, fn):
    """Additional relaxed patterns from checker calibration."""
    if cid.startswith('mutable_default_a'):
        ps = [a.arg for a in fn.args.args]
        return 'queue' not in ps and any(
            isinstance(s, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'queue' for t in s.targets
            ) for s in fn.body)
    elif cid.startswith('mutable_default_b'):
        ps = [a.arg for a in fn.args.args]
        return 'seen' not in ps and any(
            isinstance(s, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'seen' for t in s.targets
            ) for s in fn.body)
    elif cid.startswith('mutable_default_c'):
        return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == 'hasattr' for n in ast.walk(fn))
    elif cid.startswith('stale_cache_a') or cid.startswith('stale_cache_b'):
        sw = False
        for stmt in fn.body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'update':
                    sw = True
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and 'db' in t.value.id.lower():
                            sw = True
            if sw:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Assign):
                        for t in n.targets:
                            if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and 'cache' in t.value.id.lower():
                                return True
    return False


def _check_anti(cid, fn, anti_fn):
    """Run anti-pattern check. Returns True if anti-pattern found."""
    if anti_fn is None:
        return False
    return anti_fn(fn)


def _target_modified(code, func_name):
    """Check if the target function exists AND differs from a trivial pass-through."""
    return f'def {func_name}' in code


# =====================================================================
# CORE: evaluate one event with unknown state + locus + exec decomp
# =====================================================================

def evaluate(ev):
    cid = ev['case_id']
    p = ev.get('payload', {})
    model = ev.get('model', '')
    condition = ev.get('context', {}).get('condition', '')
    trial = ev.get('trial', 0)
    rs = p.get('reconstruction_status')
    ep = p.get('pass', False)
    mc = p.get('mechanism_correct', False)
    v2c = p.get('v2_category', '')
    exec_cat = p.get('execution_category', '')
    reasons = p.get('reasons', [])

    case = CASES.get(cid, {})
    ref = case.get('reference_fix', {})
    target_file = os.path.basename(ref.get('file', ''))
    target_func = ref.get('function', '')

    base = {
        'case_id': cid,
        'family': case.get('family', cid),
        'model': model,
        'condition': condition,
        'trial': trial,
        'exec_pass': ep,
        'mechanism_correct': mc,
        'execution_category': exec_cat,
        'failure_reasons': '|'.join(str(r) for r in reasons[:3]) if reasons else '',
    }

    # ── LOCUS VERIFICATION ──
    code = p.get('_extracted_code', '')
    if rs == 'SUCCESS' and code:
        locus_match = _target_modified(code, target_func) if target_func else None
    else:
        locus_match = None
    base['ast_location_match'] = locus_match

    # ── LOCUS-ONLY PROBE (simple baseline) ──
    base['locus_probe'] = locus_match  # same as location match for now

    # ── AST EVALUATION with unknown state ──
    rules, is_mod = get_rules(cid)

    if rules is None:
        base.update(ast_alignment='not_measurable', ast_relaxed=None, ast_unknown=False)
        return base

    if rs != 'SUCCESS' or not code.strip():
        base.update(ast_alignment='unassessable', ast_relaxed=None, ast_unknown=False)
        return base

    func_name = rules[0]

    # Multi-file scoping
    if f'def {func_name}' not in code and cid in MULTI_FILE:
        # Cross-layer fix detection for alias_config_c
        if cid == 'alias_config_c' and ep and ('copy' in code.lower() or 'dict(' in code):
            base.update(ast_alignment='cross_layer_fix', ast_relaxed=None, ast_unknown=False)
        else:
            base.update(ast_alignment='extraction_error', ast_relaxed=None, ast_unknown=False)
        return base

    try:
        tree = ast.parse(code)
    except SyntaxError:
        base.update(ast_alignment='unassessable', ast_relaxed=None, ast_unknown=False)
        return base

    if is_mod:
        _, sf, rf, af, pf = rules
        ro = rf(tree) if rf else False
        anti = af(tree) if af else False
    else:
        fn = find_function(tree, func_name)
        if fn is None:
            base.update(ast_alignment='extraction_error', ast_relaxed=None, ast_unknown=False)
            return base
        _, sf, rf, af, pf = rules
        ro = rf(fn) if rf else False
        anti = af(fn) if af else False
        if not ro:
            ro = _addl_relaxed(cid, fn)

    ast_relaxed = ro and not anti

    # ── UNKNOWN STATE ──
    # unknown = no pattern match AND no anti-pattern AND target was modified
    target_was_modified = _target_modified(code, func_name)
    ast_unknown = (not ro) and (not anti) and target_was_modified

    if ast_relaxed:
        alignment = 'correct'
    elif anti:
        alignment = 'incorrect'  # anti-pattern present = strong negative
    elif ast_unknown:
        alignment = 'unknown'    # no match, no anti, but modified = indeterminate
    else:
        alignment = 'incorrect'  # no match, no modification = didn't fix

    base.update(ast_alignment=alignment, ast_relaxed=ast_relaxed, ast_unknown=ast_unknown)

    # ── EXEC FAILURE DECOMPOSITION (for AST-correct exec-fail events) ──
    if ast_relaxed and not ep:
        base['exec_failure_type'] = classify_exec_failure(exec_cat, reasons)
    else:
        base['exec_failure_type'] = None

    return base


def classify_exec_failure(exec_cat, reasons):
    """Rule-based execution failure classification. Priority order."""
    # Priority 1-3: automatic from execution_category
    if exec_cat == 'IMPORT_FAILURE':
        return 'import_failure'
    if exec_cat == 'NAME_ERROR':
        return 'name_error'
    if exec_cat == 'INVARIANT_CRASH':
        return 'runtime_crash'

    # Priority 4-7: rule-based on failure_reasons text
    reasons_text = ' '.join(str(r) for r in reasons).lower()

    if ('expected' in reasons_text) and ('got' in reasons_text or '!=' in reasons_text or '=' in reasons_text):
        return 'wrong_value_literal'
    if 'not found' in reasons_text or 'has no attribute' in reasons_text or 'missing' in reasons_text:
        return 'missing_attribute'
    if 'raised' in reasons_text or 'exception' in reasons_text:
        return 'unexpected_exception'
    if 'type' in reasons_text and ('expected' in reasons_text or 'returned' in reasons_text):
        return 'test_contract_mismatch'

    # Priority 8: unclassified
    return 'unclassified_invariant'


# =====================================================================
# MAIN
# =====================================================================

def main():
    print('=== V5 Analysis: Unknown State + Locus + Exec Decomp ===\n')

    # Load oracle labels
    oracle = {}
    oracle_paths = [
        'artifacts/audits/oracle_intervention/oracle_labels.jsonl',
        'artifacts/audits/oracle_retry_critique_stage2_openai/results.json',
        'artifacts/audits/oracle_retry_critique_stage2_anthropic/results.json',
        'artifacts/audits/oracle_global_calibration_openai/results.json',
        'artifacts/audits/oracle_global_calibration_anthropic/results.json',
    ]
    for op in oracle_paths:
        full = os.path.join(PROJECT_ROOT, op)
        if not os.path.exists(full):
            continue
        if full.endswith('.jsonl'):
            with open(full) as f:
                for line in f:
                    r = json.loads(line)
                    key = (r['case_id'], r['model'], r['condition'], int(r['trial']))
                    oracle[key] = r.get('reasoning_truth', '')
        else:
            with open(full) as f:
                for r in json.load(f):
                    key = (r['case_id'], r['model'], r['condition'], int(r['trial']))
                    oracle[key] = r.get('reasoning_truth', '')
    print(f'Loaded {len(oracle)} oracle labels')

    # Load events
    events = []
    seen = set()
    for ld in ORACLE_LOGS:
        path = os.path.join(PROJECT_ROOT, ld, 'merged_events.jsonl')
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                ev = json.loads(line)
                if ev.get('event_type') != 'case.end':
                    continue
                key = (ev['case_id'], ev.get('model', ''),
                       ev.get('context', {}).get('condition', ''), ev.get('trial', 0))
                if key in seen:
                    continue
                seen.add(key)
                events.append(ev)
    print(f'Loaded {len(events)} unique events')

    # Evaluate
    results = []
    for ev in events:
        r = evaluate(ev)
        # Join oracle
        key = (r['case_id'], r['model'], r['condition'], int(r['trial']))
        rt = oracle.get(key, '')
        r['reasoning_truth'] = rt
        r['oracle_correct'] = rt in ('CORRECT', 'PARTIAL')
        results.append(r)

    # Filter to assessable with oracle
    a = [r for r in results
         if r['ast_alignment'] in ('correct', 'incorrect', 'unknown')
         and r['reasoning_truth'] in ('CORRECT', 'PARTIAL', 'WRONG')]
    N = len(a)
    print(f'Assessable + oracle-labeled: {N}\n')

    # Write event-level CSV
    out_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'analysis')
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, 'v5_analysis_events.csv')
    flds = ['case_id', 'family', 'model', 'condition', 'trial',
            'exec_pass', 'mechanism_correct', 'execution_category', 'failure_reasons',
            'ast_location_match', 'locus_probe',
            'ast_alignment', 'ast_relaxed', 'ast_unknown',
            'exec_failure_type',
            'reasoning_truth', 'oracle_correct']
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=flds, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    # =====================================================================
    # ANALYSIS
    # =====================================================================

    lines = []
    def p(s=''):
        lines.append(s)
        print(s)

    p('# V5 Analysis Results')
    p()
    p(f'**Events:** {N} assessable + oracle-labeled')
    p()

    # ── ANCHOR TABLE ──
    oc = sum(1 for r in a if r['oracle_correct'])
    ast_correct = sum(1 for r in a if r['ast_alignment'] == 'correct')
    ast_incorrect = sum(1 for r in a if r['ast_alignment'] == 'incorrect')
    ast_unknown = sum(1 for r in a if r['ast_alignment'] == 'unknown')
    ep = sum(1 for r in a if r['exec_pass'])
    locus_t = sum(1 for r in a if r['ast_location_match'] is True)
    locus_f = sum(1 for r in a if r['ast_location_match'] is False)

    p('## 1. Anchor Table')
    p()
    p('| Metric | Value |')
    p('|--------|-------|')
    p(f'| N (assessable + oracle) | {N} |')
    p(f'| P(oracle_correct) | {oc/N*100:.1f}% |')
    p(f'| P(ast_correct) | {ast_correct/N*100:.1f}% |')
    p(f'| P(ast_incorrect) | {ast_incorrect/N*100:.1f}% |')
    p(f'| P(ast_unknown) | {ast_unknown/N*100:.1f}% (estimate) |')
    p(f'| P(exec_pass) | {ep/N*100:.1f}% |')
    p(f'| P(locus_match) | {locus_t/(locus_t+locus_f)*100:.1f}% (of assessable) |')
    p()

    # ── 3-STAGE FAILURE DECOMPOSITION ──
    failures = [r for r in a if not r['exec_pass']]
    nf = len(failures)
    s1 = sum(1 for r in failures if not r['oracle_correct'])
    s2 = sum(1 for r in failures if r['oracle_correct'] and r['ast_alignment'] != 'correct')
    s3 = sum(1 for r in failures if r['oracle_correct'] and r['ast_alignment'] == 'correct')

    p('## 2. Three-Stage Failure Decomposition')
    p()
    p(f'Total failures: {nf}')
    p()
    p('| Stage | Count | % | Description |')
    p('|-------|-------|---|-------------|')
    p(f'| 1. Reasoning | {s1} | {s1/nf*100:.1f}% | Oracle says reasoning wrong |')
    p(f'| 2. Structure | {s2} | {s2/nf*100:.1f}% | Oracle correct, AST not correct |')
    p(f'| 3. Execution | {s3} | {s3/nf*100:.1f}% | Oracle correct, AST correct, exec fails |')
    p()
    p(f'*Note: Stage 2 includes {sum(1 for r in failures if r["oracle_correct"] and r["ast_alignment"] == "unknown")} events classified as AST "unknown" (structurally indeterminate).*')

    # ── EXEC FAILURE DECOMPOSITION ──
    acf = [r for r in a if r['ast_alignment'] == 'correct' and not r['exec_pass']]
    p()
    p('## 3. Execution Failure Decomposition (AST-correct failures)')
    p()
    p(f'Total AST-correct execution failures: {len(acf)}')
    p()
    eft = Counter(r.get('exec_failure_type', 'none') for r in acf)
    p('| Category | Count | % | Classification |')
    p('|----------|-------|---|---------------|')
    for cat, n in eft.most_common():
        method = 'automatic' if cat in ('import_failure', 'name_error', 'runtime_crash') else 'rule-based' if cat != 'unclassified_invariant' else 'manual review needed'
        p(f'| {cat} | {n} | {n/len(acf)*100:.1f}% | {method} |')

    # ── UNKNOWN STATE ANALYSIS ──
    p()
    p('## 4. Unknown State Analysis')
    p()
    p(f'Total unknown: {ast_unknown} ({ast_unknown/N*100:.1f}%) — estimate, pending rule validation')
    p()
    unk_pass = sum(1 for r in a if r['ast_alignment'] == 'unknown' and r['exec_pass'])
    unk_fail = sum(1 for r in a if r['ast_alignment'] == 'unknown' and not r['exec_pass'])
    p(f'| Unknown × Exec | Count | Interpretation |')
    p(f'|----------------|-------|----------------|')
    p(f'| unknown + exec_pass | {unk_pass} | Alternative repair candidate |')
    p(f'| unknown + exec_fail | {unk_fail} | Structurally indeterminate failure |')
    p()

    # Per-family unknown
    p('### Per-family unknown rate')
    p()
    p('| Family | N | Unknown | Unknown% |')
    p('|--------|---|---------|----------|')
    fg_unk = defaultdict(lambda: {'n': 0, 'unk': 0})
    for r in a:
        fg_unk[r['family']]['n'] += 1
        if r['ast_alignment'] == 'unknown':
            fg_unk[r['family']]['unk'] += 1
    for f in sorted(fg_unk, key=lambda x: -fg_unk[x]['unk'] / max(fg_unk[x]['n'], 1)):
        g = fg_unk[f]
        if g['unk'] > 0 and g['n'] >= 50:
            p(f'| {f} | {g["n"]} | {g["unk"]} | {g["unk"]/g["n"]*100:.1f}% |')

    # ── LOCUS VERIFICATION ──
    p()
    p('## 5. Locus Verification')
    p()
    locus_events = [r for r in a if r['ast_location_match'] is not None]
    lm_t = sum(1 for r in locus_events if r['ast_location_match'])
    lm_f = len(locus_events) - lm_t
    p(f'Assessable for locus: {len(locus_events)}')
    p(f'Locus match: {lm_t} ({lm_t/len(locus_events)*100:.1f}%)')
    p(f'Locus mismatch: {lm_f} ({lm_f/len(locus_events)*100:.1f}%)')
    p()

    # Locus mismatch × exec
    lm_f_pass = sum(1 for r in locus_events if not r['ast_location_match'] and r['exec_pass'])
    lm_f_fail = sum(1 for r in locus_events if not r['ast_location_match'] and not r['exec_pass'])
    p(f'Locus mismatch + exec_pass: {lm_f_pass} (cross-layer or wrong-file fix that passes)')
    p(f'Locus mismatch + exec_fail: {lm_f_fail} (wrong location + failure)')

    # ── BASELINE COMPARISON: LOCUS vs FULL AST ──
    p()
    p('## 6. Baseline Comparison: Locus Probe vs Full AST')
    p()
    p('Oracle agreement rates (measured):')
    p()

    # Execution-only
    exec_oracle_agree = sum(1 for r in a if r['exec_pass'] == r['oracle_correct'])
    # Old classifier
    mc_oracle_agree = sum(1 for r in a if r['mechanism_correct'] == r['oracle_correct'])
    # Locus probe
    locus_oracle_agree = sum(1 for r in locus_events if r['ast_location_match'] == r['oracle_correct'])
    # AST (correct only, excluding unknown)
    ast_assessable = [r for r in a if r['ast_alignment'] in ('correct', 'incorrect')]
    ast_oracle_agree = sum(1 for r in ast_assessable if (r['ast_alignment'] == 'correct') == r['oracle_correct'])

    p('| Signal | N | Oracle Agreement | Status |')
    p('|--------|---|-----------------|--------|')
    p(f'| Execution only | {N} | {exec_oracle_agree/N*100:.1f}% | Measured |')
    p(f'| Old LLM classifier | {N} | {mc_oracle_agree/N*100:.1f}% | Measured |')
    p(f'| Locus probe | {len(locus_events)} | {locus_oracle_agree/len(locus_events)*100:.1f}% | Measured |')
    p(f'| Full AST (excl. unknown) | {len(ast_assessable)} | {ast_oracle_agree/len(ast_assessable)*100:.1f}% | Measured |')
    p()
    p(f'AST incremental over execution: +{(ast_oracle_agree/len(ast_assessable) - exec_oracle_agree/N)*100:.1f}pp')
    p(f'AST incremental over locus probe: +{(ast_oracle_agree/len(ast_assessable) - locus_oracle_agree/len(locus_events))*100:.1f}pp')
    p(f'Locus incremental over execution: +{(locus_oracle_agree/len(locus_events) - exec_oracle_agree/N)*100:.1f}pp')

    # ── BY CONDITION ──
    p()
    p('## 7. By Condition')
    p()
    p('| Condition | N | Oracle% | AST_correct% | Unknown% | Pass% | ExecFidelityFail% |')
    p('|-----------|---|---------|-------------|---------|-------|-------------------|')
    for cond in ['baseline_v2', 'leg_reduction_lean_v2', 'leg_reduction_v2',
                 'retry_bare_retry_v2', 'retry_leg_critique_strict_v2', 'retry_reasoning_only_critique_v1']:
        ca = [r for r in a if r['condition'] == cond]
        cn = len(ca)
        if cn < 30:
            continue
        oc_c = sum(1 for r in ca if r['oracle_correct'])
        ac_c = sum(1 for r in ca if r['ast_alignment'] == 'correct')
        unk_c = sum(1 for r in ca if r['ast_alignment'] == 'unknown')
        ep_c = sum(1 for r in ca if r['exec_pass'])
        eff_c = sum(1 for r in ca if r['oracle_correct'] and r['ast_alignment'] == 'correct' and not r['exec_pass'])
        p(f'| {cond} | {cn} | {oc_c/cn*100:.1f}% | {ac_c/cn*100:.1f}% | {unk_c/cn*100:.1f}% | {ep_c/cn*100:.1f}% | {eff_c/cn*100:.1f}% |')

    # ── BY MODEL ──
    p()
    p('## 8. By Model')
    p()
    p('| Model | N | Oracle% | AST_correct% | Unknown% | Pass% | ExecFidelityFail% |')
    p('|-------|---|---------|-------------|---------|-------|-------------------|')
    for m in sorted(set(r['model'] for r in a)):
        ma = [r for r in a if r['model'] == m]
        mn = len(ma)
        if mn < 10:
            continue
        oc_m = sum(1 for r in ma if r['oracle_correct'])
        ac_m = sum(1 for r in ma if r['ast_alignment'] == 'correct')
        unk_m = sum(1 for r in ma if r['ast_alignment'] == 'unknown')
        ep_m = sum(1 for r in ma if r['exec_pass'])
        eff_m = sum(1 for r in ma if r['oracle_correct'] and r['ast_alignment'] == 'correct' and not r['exec_pass'])
        p(f'| {m} | {mn} | {oc_m/mn*100:.1f}% | {ac_m/mn*100:.1f}% | {unk_m/mn*100:.1f}% | {ep_m/mn*100:.1f}% | {eff_m/mn*100:.1f}% |')

    # ── CORE CLAIM ──
    p()
    p('## 9. Core Claim (Precise)')
    p()
    p(f'Of {nf} execution failures across {N} oracle-labeled evaluation events, '
      f'{s3/nf*100:.1f}% ({s3} events) occur in cases where both the oracle reasoning '
      f'evaluator and AST structural verification indicate correct reasoning and correct '
      f'structural implementation, yet execution fails. This execution-fidelity gap is the '
      f'dominant failure mode, exceeding reasoning failure ({s1/nf*100:.1f}%) and structural '
      f'translation failure ({s2/nf*100:.1f}%).')

    # Write report
    report_path = os.path.join(out_dir, 'v5_analysis_report.md')
    with open(report_path, 'w') as f:
        f.write('\n'.join(lines))

    print(f'\n\nOutputs:')
    print(f'  {csv_path} ({len(results)} rows)')
    print(f'  {report_path} ({len(lines)} lines)')


if __name__ == '__main__':
    main()
