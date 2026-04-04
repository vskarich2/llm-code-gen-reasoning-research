"""Full retrospective AST evaluation on oracle-evaluated logs.
47 AST-measurable cases, 12 log directories, 22K+ events."""

import ast, csv, json, os, sys
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(__file__))
from checkers import CASE_RULES, find_function
from checker_fixes import CASE_RULES_OVERRIDES, MODULE_LEVEL_CASES, NOT_AST_MEASURABLE

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Oracle-evaluated log directories
ORACLE_LOGS = [
    "logs/v2_targeted_50trial_canonical",
    "logs/v2_full_4model_10trial_canonical",
    "logs/v2_targeted_50trial_tranche2",
    "logs/v2_targeted_50trial_tranche4",
    "logs/v2_targeted_50trial_tranche3",
    "logs/v2_anthropic_50trial_v3",
    "logs/v2_anthropic_50trial_v2",
    "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_haiku45",
    "logs/v2_anthropic_sonnet46_v2",
    "logs/v2_gpt5_50trial",
    "logs/v2_gpt5_50trial_v2",
]

with open(os.path.join(PROJECT_ROOT, 'case_data/cases_v2.json')) as f:
    CASES = {c['id']: c for c in json.load(f)}
MULTI_FILE = {cid for cid, c in CASES.items() if len(c.get('code_files', [])) > 1}


def get_rules(case_id):
    """Get CLAUDE_RULES for a case. Returns (rules_tuple, is_module_level) or (None, False)."""
    if case_id in NOT_AST_MEASURABLE:
        return None, False
    if case_id in CASE_RULES_OVERRIDES:
        return CASE_RULES_OVERRIDES[case_id], False
    if case_id in MODULE_LEVEL_CASES:
        return MODULE_LEVEL_CASES[case_id], True
    if case_id in CASE_RULES:
        return CASE_RULES[case_id], False
    return None, False


def _additional_relaxed(case_id, fn):
    """Additional relaxed patterns from rev1 audit."""
    if case_id.startswith('mutable_default_a'):
        ps = [a.arg for a in fn.args.args]
        if 'queue' not in ps:
            for s in fn.body:
                if isinstance(s, ast.Assign):
                    for t in s.targets:
                        if isinstance(t, ast.Name) and t.id == 'queue': return True
    elif case_id.startswith('mutable_default_b'):
        ps = [a.arg for a in fn.args.args]
        if 'seen' not in ps:
            for s in fn.body:
                if isinstance(s, ast.Assign):
                    for t in s.targets:
                        if isinstance(t, ast.Name) and t.id == 'seen': return True
    elif case_id.startswith('mutable_default_c'):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'hasattr':
                return True
    elif case_id.startswith('stale_cache_a') or case_id.startswith('stale_cache_b'):
        # Write-through pattern
        sw = False
        for stmt in fn.body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'update': sw = True
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and 'db' in t.value.id.lower(): sw = True
            if sw:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Assign):
                        for t in n.targets:
                            if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and 'cache' in t.value.id.lower(): return True
    return False


def _detect_partial(case_id, fn, relaxed_ok, anti_found):
    """Broadened partial detection."""
    if relaxed_ok and not anti_found: return False
    if relaxed_ok and anti_found: return True

    from checkers import _call_name as cn, _SIDE_EFFECT_NAMES as SE, _INVALIDATE_NAMES as INV

    if case_id.startswith('stale_cache'):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and any(x in cn(n).lower() for x in ('cache','invalidat','pop','del','clear')): return True
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and 'cache' in t.value.id.lower(): return True
    if case_id.startswith('mutable_default'):
        has_mutable = any(isinstance(d, (ast.List, ast.Set, ast.Dict)) for d in fn.args.defaults)
        if not has_mutable: return True
    if case_id.startswith('effect_order'):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and cn(n) in SE: return True
    if case_id.startswith('use_before_set'):
        for s in fn.body:
            if isinstance(s, ast.If) and s.orelse: return True
        if sum(1 for n in ast.walk(fn) if isinstance(n, ast.Return)) >= 2: return True
    if case_id.startswith('alias_config'):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                for a in getattr(n, 'args', []):
                    if isinstance(a, ast.Name) and a.id == 'DEFAULTS': return True
    if case_id.startswith('partial_rollback') or case_id == 'invariant_partial_fail':
        for n in ast.walk(fn):
            if isinstance(n, ast.Try) and n.handlers:
                for h in n.handlers:
                    if len(h.body) > 1: return True
    return False


def cross_layer(cid, ev):
    p = ev.get('payload', {})
    code = p.get('_extracted_code', '')
    if cid == 'alias_config_c' and p.get('pass', False):
        if 'copy' in code.lower() or 'dict(' in code: return True
    return False


def evaluate(ev):
    cid = ev['case_id']
    p = ev.get('payload', {})
    model = ev.get('model', '')
    condition = ev.get('context', {}).get('condition', '')
    rs = p.get('reconstruction_status')
    ep = p.get('pass', False)
    mc = p.get('mechanism_correct', False)
    v2c = p.get('v2_category', '')
    exec_cat = p.get('execution_category', '')
    reasons = p.get('reasons', [])

    rules, is_module = get_rules(cid)
    tf = os.path.basename(CASES.get(cid, {}).get('reference_fix', {}).get('file', ''))

    base = {'case_id': cid, 'family': CASES.get(cid, {}).get('family', cid),
            'model': model, 'condition': condition, 'exec_pass': ep,
            'mechanism_correct': mc, 'reconstruction_status': rs or '',
            'v2_category': v2c, 'target_file': tf,
            'execution_category': exec_cat,
            'failure_reasons': '|'.join(str(r) for r in reasons[:3]) if reasons else ''}

    if rules is None:
        base.update(extraction_status='not_measurable', cross_layer_fix=False,
                    ast_strict=False, ast_relaxed=False, ast_partial=False,
                    ast_final_label='not_measurable', seg_flag=False)
        return base

    if rs != 'SUCCESS':
        base.update(extraction_status='recon_failed', cross_layer_fix=False,
                    ast_strict=False, ast_relaxed=False, ast_partial=False,
                    ast_final_label='unassessable', seg_flag=False)
        return base

    code = p.get('_extracted_code', '')
    if not code.strip():
        base.update(extraction_status='empty', cross_layer_fix=False,
                    ast_strict=False, ast_relaxed=False, ast_partial=False,
                    ast_final_label='unassessable', seg_flag=False)
        return base

    func_name = rules[0]
    has_target = f'def {func_name}' in code

    if not has_target and cid in MULTI_FILE:
        cl = cross_layer(cid, ev)
        base.update(extraction_status='wrong_file', cross_layer_fix=cl,
                    ast_strict=False, ast_relaxed=False, ast_partial=False,
                    ast_final_label='cross_layer_fix' if cl else 'extraction_error',
                    seg_flag=False)
        return base

    try:
        tree = ast.parse(code)
    except SyntaxError:
        base.update(extraction_status='syntax_error', cross_layer_fix=False,
                    ast_strict=False, ast_relaxed=False, ast_partial=False,
                    ast_final_label='unassessable', seg_flag=False)
        return base

    if is_module:
        _, strict_fn, relaxed_fn, anti_fn, partial_fn = rules
        so = strict_fn(tree)
        ro = relaxed_fn(tree)
        anti = anti_fn(tree) if anti_fn else False
        ast_s = so and not anti
        ast_r = ro and not anti
        ast_p = False
        if ast_s: lbl = 'strict_correct'
        elif ast_r: lbl = 'relaxed_correct'
        else: lbl = 'wrong'
    else:
        fn = find_function(tree, func_name)
        if fn is None:
            base.update(extraction_status='func_not_found', cross_layer_fix=False,
                        ast_strict=False, ast_relaxed=False, ast_partial=False,
                        ast_final_label='extraction_error', seg_flag=False)
            return base

        _, strict_fn, relaxed_fn, anti_fn, partial_fn = rules
        so = strict_fn(fn)
        ro = relaxed_fn(fn)
        anti = anti_fn(fn) if anti_fn else False

        if not ro:
            ro = _additional_relaxed(cid, fn)

        ast_s = so and not anti
        ast_r = ro and not anti
        ast_p = _detect_partial(cid, fn, ro, anti)

        if ast_s: lbl = 'strict_correct'
        elif ast_r: lbl = 'relaxed_correct'
        elif ast_p: lbl = 'partial'
        else: lbl = 'wrong'

    base.update(extraction_status='ok', cross_layer_fix=False,
                ast_strict=ast_s, ast_relaxed=ast_r, ast_partial=ast_p,
                ast_final_label=lbl, seg_flag=ast_r and not ep)
    return base


def main():
    print('=== Full AST Evaluation — 47 Cases, 12 Oracle Logs ===\n')

    # Load events
    events = []
    for logdir in ORACLE_LOGS:
        path = os.path.join(PROJECT_ROOT, logdir, 'merged_events.jsonl')
        if not os.path.exists(path):
            print(f'  WARN: {path} not found')
            continue
        with open(path) as f:
            for line in f:
                ev = json.loads(line)
                if ev.get('event_type') == 'case.end':
                    events.append(ev)
    print(f'Loaded {len(events)} case.end events from {len(ORACLE_LOGS)} log dirs\n')

    results = [evaluate(ev) for ev in events]

    # Write CSV
    csv_path = os.path.join(PROJECT_ROOT, 'analysis', 'ast_full_58case_results.csv')
    os.makedirs(os.path.join(PROJECT_ROOT, 'analysis'), exist_ok=True)
    flds = ['case_id','family','model','condition','exec_pass','mechanism_correct',
            'reconstruction_status','extraction_status','cross_layer_fix',
            'ast_strict','ast_relaxed','ast_partial','ast_final_label',
            'seg_flag','target_file','execution_category','failure_reasons']
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=flds, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)
    print(f'Results: {csv_path} ({len(results)} rows)\n')

    # ── ANALYSIS ──
    assessable = [r for r in results if r['ast_final_label'] not in
                  ('unassessable','extraction_error','cross_layer_fix','not_measurable')]
    not_meas = [r for r in results if r['ast_final_label'] == 'not_measurable']
    cross_layer_evts = [r for r in results if r['ast_final_label'] == 'cross_layer_fix']
    ext_err = [r for r in results if r['ast_final_label'] == 'extraction_error']
    unassess = [r for r in results if r['ast_final_label'] == 'unassessable']
    N = len(assessable)

    print(f'Total events: {len(results)}')
    print(f'  Assessable: {N}')
    print(f'  Not measurable: {len(not_meas)}')
    print(f'  Cross-layer fix: {len(cross_layer_evts)}')
    print(f'  Extraction error: {len(ext_err)}')
    print(f'  Unassessable: {len(unassess)}')

    labels = Counter(r['ast_final_label'] for r in assessable)
    print(f'\nAST labels: {dict(labels.most_common())}')

    # 2x2
    r_ts = sum(1 for r in assessable if r['ast_relaxed'] and r['exec_pass'])
    r_acf = sum(1 for r in assessable if r['ast_relaxed'] and not r['exec_pass'])
    r_lf = sum(1 for r in assessable if not r['ast_relaxed'] and r['exec_pass'])
    r_ff = sum(1 for r in assessable if not r['ast_relaxed'] and not r['exec_pass'])
    ac = r_ts + r_acf

    print(f'\n{"="*60}')
    print(f'RELAXED 2x2 (N={N})')
    print(f'{"="*60}')
    print(f"{'':20s} {'Exec Pass':>12s} {'Exec Fail':>12s}")
    print(f"{'AST Correct':20s} {r_ts:>12d} {r_acf:>12d}")
    print(f"{'AST Incorrect':20s} {r_lf:>12d} {r_ff:>12d}")

    print(f'\n=== ANCHOR TABLE ===')
    print(f'P(mechanism_correct)       = {sum(1 for r in assessable if r["mechanism_correct"])/N*100:.1f}%')
    print(f'P(ast_correct)             = {ac/N*100:.1f}%')
    print(f'P(exec_pass)               = {(r_ts+r_lf)/N*100:.1f}%')
    print(f'P(exec_fail | ast_correct) = {r_acf/max(ac,1)*100:.1f}%')
    print(f'AST-evaluator agreement    = {sum(1 for r in assessable if r["ast_relaxed"]==r["mechanism_correct"])/N*100:.1f}%')
    print(f'LUCKY_FIX                  = {r_lf/N*100:.1f}%')
    print(f'AST_partial                = {labels.get("partial",0)/N*100:.1f}% ({labels.get("partial",0)})')
    print(f'Cross-layer fixes          = {len(cross_layer_evts)}')

    # Per-family
    print(f'\n{"="*60}')
    print(f'P(exec_fail | ast_correct) BY FAMILY')
    print(f'{"="*60}')
    fg = defaultdict(lambda: {'ac':0,'acf':0,'n':0,'ep':0,'part':0,'lf':0})
    for r in assessable:
        fam = r['family']
        fg[fam]['n'] += 1
        if r['exec_pass']: fg[fam]['ep'] += 1
        if r['ast_relaxed']:
            fg[fam]['ac'] += 1
            if not r['exec_pass']: fg[fam]['acf'] += 1
        if r['ast_partial']: fg[fam]['part'] += 1
        if not r['ast_relaxed'] and r['exec_pass']: fg[fam]['lf'] += 1

    print(f"\n{'Family':<25s} {'N':>5s} {'AST%':>6s} {'Pass%':>6s} {'P(F|A)':>7s} {'Part':>5s} {'LF':>5s}")
    for fam in sorted(fg.keys(), key=lambda x: -fg[x]['acf']/max(fg[x]['ac'],1)):
        g = fg[fam]
        pfa = g['acf']/max(g['ac'],1)*100
        print(f"{fam:<25s} {g['n']:>5d} {g['ac']/g['n']*100:>5.1f}% {g['ep']/g['n']*100:>5.1f}% {pfa:>6.1f}% {g['part']:>5d} {g['lf']:>5d}")

    # Per-model
    print(f'\n{"="*60}')
    print(f'P(exec_fail | ast_correct) BY MODEL')
    print(f'{"="*60}')
    mg = defaultdict(lambda: {'ac':0,'acf':0,'n':0,'ep':0})
    for r in assessable:
        m = r['model']
        mg[m]['n'] += 1
        if r['exec_pass']: mg[m]['ep'] += 1
        if r['ast_relaxed']:
            mg[m]['ac'] += 1
            if not r['exec_pass']: mg[m]['acf'] += 1

    print(f"\n{'Model':<30s} {'N':>6s} {'AST%':>6s} {'Pass%':>6s} {'P(F|A)':>7s}")
    for m in sorted(mg.keys(), key=lambda x: -mg[x]['acf']/max(mg[x]['ac'],1)):
        g = mg[m]
        pfa = g['acf']/max(g['ac'],1)*100
        print(f"{m:<30s} {g['n']:>6d} {g['ac']/g['n']*100:>5.1f}% {g['ep']/g['n']*100:>5.1f}% {pfa:>6.1f}%")

    # Per-condition
    print(f'\n{"="*60}')
    print(f'BY CONDITION')
    print(f'{"="*60}')
    cg = defaultdict(lambda: {'ac':0,'acf':0,'n':0,'ep':0})
    for r in assessable:
        c = r['condition']
        cg[c]['n'] += 1
        if r['exec_pass']: cg[c]['ep'] += 1
        if r['ast_relaxed']:
            cg[c]['ac'] += 1
            if not r['exec_pass']: cg[c]['acf'] += 1

    print(f"\n{'Condition':<30s} {'N':>6s} {'AST%':>6s} {'Pass%':>6s} {'P(F|A)':>7s}")
    for c in sorted(cg.keys(), key=lambda x: -cg[x]['acf']/max(cg[x]['ac'],1)):
        g = cg[c]
        pfa = g['acf']/max(g['ac'],1)*100
        print(f"{c:<30s} {g['n']:>6d} {g['ac']/g['n']*100:>5.1f}% {g['ep']/g['n']*100:>5.1f}% {pfa:>6.1f}%")

    # Execution failure decomposition
    print(f'\n{"="*60}')
    print(f'EXECUTION FAILURE DECOMPOSITION (AST-correct failures)')
    print(f'{"="*60}')
    acf_events = [r for r in assessable if r['ast_relaxed'] and not r['exec_pass']]
    exec_cats = Counter(r.get('execution_category', '?') for r in acf_events)
    print(f'\nTotal AST-correct failures: {len(acf_events)}')
    for c, n in exec_cats.most_common():
        print(f'  {c}: {n} ({n/len(acf_events)*100:.1f}%)')

    # Causal decomposition
    print(f'\n{"="*60}')
    print(f'CAUSAL FAILURE DECOMPOSITION')
    print(f'{"="*60}')
    total_fail = sum(1 for r in assessable if not r['exec_pass'])
    rf = sum(1 for r in assessable if not r['mechanism_correct'] and not r['exec_pass'])
    sf = sum(1 for r in assessable if r['mechanism_correct'] and not r['ast_relaxed'] and not r['exec_pass'])
    ef = sum(1 for r in assessable if r['ast_relaxed'] and not r['exec_pass'])
    print(f'\nTotal failures: {total_fail}')
    print(f'  Stage 1 (reasoning):  {rf} ({rf/max(total_fail,1)*100:.1f}%)')
    print(f'  Stage 2 (structure):  {sf} ({sf/max(total_fail,1)*100:.1f}%)')
    print(f'  Stage 3 (execution):  {ef} ({ef/max(total_fail,1)*100:.1f}%)')

    print(f'\nDone.')


if __name__ == '__main__':
    main()
