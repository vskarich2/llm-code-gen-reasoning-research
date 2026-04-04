"""Recover and test Haiku's malformed JSON responses."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = str(Path(__file__).parent.parent)


def run_recovered_eval(case_id, code_files, cases_data, timeout=15):
    """Run recovered code through the canonical test harness."""
    case = next(c for c in cases_data if c["id"] == case_id)
    difficulty = case.get("difficulty", "a").lower()

    pkg_dir = Path(tempfile.mkdtemp(prefix=f"t3_recover_{case_id}_"))
    try:
        # pkg/
        pkg = pkg_dir / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        for rel_path, content in code_files.items():
            filename = rel_path.rsplit("/", 1)[-1]
            (pkg / filename).write_text(content)

        # harness/
        harness_dst = pkg_dir / "harness"
        harness_dst.mkdir()
        harness_src = Path(PROJECT_ROOT) / "harness" / "run_case.py"
        shutil.copy2(str(harness_src), str(harness_dst / "run_case.py"))

        # case_meta.json
        meta = {
            "case_id": case_id,
            "family": case.get("family", ""),
            "difficulty": difficulty,
            "project_root": PROJECT_ROOT,
            "code_files": case["code_files"],
        }
        (pkg_dir / "case_meta.json").write_text(json.dumps(meta))

        # Run
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{pkg / '.'}{os.pathsep}{PROJECT_ROOT}"
        cmd = [sys.executable, "harness/run_case.py"]
        result = subprocess.run(
            cmd, cwd=str(pkg_dir), capture_output=True,
            text=True, timeout=timeout, env=env,
        )
        if result.returncode != 0:
            return False, [result.stderr[:100] if result.stderr else "nonzero exit"]
        out = json.loads(result.stdout)
        passed = out.get("passed", out.get("pass", False))
        reasons = out.get("failure_reasons", out.get("reasons", []))
        if out.get("error_message"):
            reasons = [out["error_message"]] + reasons
        return passed, reasons
    except subprocess.TimeoutExpired:
        return False, ["timeout"]
    except Exception as ex:
        return False, [str(ex)[:100]]
    finally:
        shutil.rmtree(pkg_dir, ignore_errors=True)


def recover_files(raw):
    """Try to extract files dict from malformed JSON."""
    # Strategy 1: valid JSON
    try:
        parsed = json.loads(raw)
        if "files" in parsed:
            return parsed["files"], "valid_json"
    except Exception:
        pass

    # Strategy 2: structural extraction for triple-quoted values
    # Haiku wraps file content in """, and Python docstrings inside
    # also use """. We find file paths, then extract content between
    # the opening """ after the path and the closing """ that is
    # followed by a comma+next-path or closing brace.
    files_match = re.search(r'"files"\s*:\s*\{', raw)
    if files_match:
        fp = re.compile(r'"(code_snippets_v2/[^"]+\.py)"\s*:\s*')
        positions = [
            (m.start(), m.end(), m.group(1))
            for m in fp.finditer(raw, files_match.end())
        ]
        if positions:
            files = {}
            for i, (start, end, filepath) in enumerate(positions):
                val_start = end
                rest = raw[val_start:].lstrip()

                # UNCHANGED
                if rest.startswith('"UNCHANGED"'):
                    continue

                # Triple-quoted value: find content between opening """
                # and the LAST """ before the next file entry or closing }
                if rest.startswith('"""'):
                    code_start = val_start + raw[val_start:].index('"""') + 3

                    # Boundary: next file path or end of files dict
                    if i + 1 < len(positions):
                        boundary = positions[i + 1][0]
                    else:
                        # Last file — boundary is the final } of the JSON
                        boundary = len(raw)

                    # Find the LAST """ before boundary
                    search_region = raw[code_start:boundary]
                    last_tq = search_region.rfind('"""')
                    if last_tq >= 0:
                        code = search_region[:last_tq]
                    else:
                        code = search_region

                    # Unescape JSON backslash sequences
                    code = code.replace('\\"', '"')
                    code = code.replace('\\\\', '\\')
                    code = code.replace('\\n', '\n')
                    code = code.replace('\\t', '\t')
                    files[filepath] = strip_fences(code)
                    continue

                # Regular quoted value
                if rest.startswith('"'):
                    # Use json.loads to properly decode the string
                    # Find the extent of the JSON string value
                    try:
                        val, _ = json.decoder.scanstring(
                            raw, val_start + raw[val_start:].index('"') + 1
                        )
                        files[filepath] = strip_fences(val)
                    except Exception:
                        pass

            if files:
                return files, "structural_extraction"

    # Strategy 3: regex extract "filepath.py": "code" pairs
    pattern = r'"(code_snippets_v2/[^"]+\.py)"\s*:\s*"((?:[^"\\]|\\.)*)"'
    matches = re.findall(pattern, raw)
    if matches:
        files = {}
        for fname, code in matches:
            try:
                code = code.encode().decode("unicode_escape")
            except Exception:
                pass
            files[fname] = strip_fences(code)
        if files:
            return files, "regex_quotes"

    return None, "unrecoverable"


def strip_fences(code):
    """Remove markdown fences and triple-quote wrappers from code."""
    if not code or code == "UNCHANGED":
        return code
    # Strip ```python ... ``` or ``` ... ```
    code = re.sub(r'^```(?:python)?\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    # Strip leading/trailing triple quotes
    if code.startswith('"""') and code.endswith('"""'):
        code = code[3:-3]
    if code.startswith("'''") and code.endswith("'''"):
        code = code[3:-3]
    return code.strip()


def main():
    bases = [
        Path("logs/v2_anthropic_50trial_v2/workers"),
        Path("logs/v2_anthropic_50trial_v3/workers"),
    ]

    cases_data = json.loads(Path("cases_v2.json").read_text())
    # Preload code file contents
    for case in cases_data:
        case["code_files_contents"] = {}
        for rel_path in case["code_files"]:
            case["code_files_contents"][rel_path] = Path(rel_path).read_text().strip()
    case_by_id = {c["id"]: c for c in cases_data}

    target_cases = ["config_shadowing", "overdetermination", "lost_update"]
    conds = ["baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"]
    cs = {"baseline_v2": "base", "leg_reduction_v2": "leg",
          "leg_reduction_lean_v2": "lean"}

    results = defaultdict(lambda: {
        "strict": [], "recovered_pass": 0,
        "recovered_fail": 0, "unrecoverable": 0,
        "fail_reasons": Counter(),
    })

    sample_count = 0
    for base_dir in bases:
        if not base_dir.exists():
            print(f"  SKIP: {base_dir} does not exist", flush=True)
            continue
        print(f"  Scanning {base_dir}...", flush=True)
        for wdir in sorted(base_dir.iterdir()):
            if not wdir.is_dir() or "haiku" not in wdir.name:
                continue

            case_id = None
            for tc in target_cases:
                if tc in wdir.name:
                    case_id = tc
                    break
            if not case_id:
                continue

            ep = wdir / "attempt_001" / "events.jsonl"
            call_file = wdir / "attempt_001" / "calls" / "000001.json"
            if not ep.exists() or not call_file.exists():
                continue

            cond = None
            strict_pass = False
            for line in open(ep):
                e = json.loads(line.strip())
                if e["event_type"] == "case.end":
                    cond = e.get("condition")
                    strict_pass = e.get("payload", {}).get("pass", False)
            if not cond:
                continue

            key = (case_id, cond)
            results[key]["strict"].append(strict_pass)

            d = json.load(open(call_file))
            raw = d.get("response_raw", "")
            files, method = recover_files(raw)

            if not files:
                results[key]["unrecoverable"] += 1
                continue

            case = case_by_id[case_id]
            code_files = {}
            for rel_path in case["code_files"]:
                code_files[rel_path] = Path(rel_path).read_text().strip()

            for fname, code in files.items():
                if code == "UNCHANGED":
                    continue
                if fname in code_files:
                    code_files[fname] = code

            try:
                passed, reasons = run_recovered_eval(
                    case_id, code_files, cases_data, timeout=15)
                if passed:
                    results[key]["recovered_pass"] += 1
                else:
                    results[key]["recovered_fail"] += 1
                    r = reasons[0] if reasons else "no_reason"
                    results[key]["fail_reasons"][str(r)[:80]] += 1
            except Exception as ex:
                results[key]["recovered_fail"] += 1
                results[key]["fail_reasons"][f"EXCEPTION: {ex!s}"[:80]] += 1

            sample_count += 1
            status = "PASS" if passed else "FAIL"
            print(f"  [{sample_count:3d}] {case_id:25s} {cs.get(cond,cond):5s} "
                  f"strict={'PASS' if strict_pass else 'FAIL':4s} "
                  f"recon={status:4s} method={method}", flush=True)

    print(f"\nProcessed {sample_count} samples\n", flush=True)
    print("HAIKU 3 — RECOVERED CODE TEST RESULTS")
    print("=" * 90)
    print(f"{'Case':25s} {'Cond':6s} {'N':>4s} "
          f"{'Strict':>10s} {'Recov Pass':>12s} {'Unrec':>6s}")
    print("-" * 90)

    for cid in target_cases:
        for cond in conds:
            key = (cid, cond)
            if key not in results:
                continue
            r = results[key]
            n = len(r["strict"])
            strict = sum(r["strict"])
            rp = r["recovered_pass"]
            rf = r["recovered_fail"]
            unrec = r["unrecoverable"]
            total_rec = rp + rf
            sc = cs.get(cond, cond)
            rec_str = (f"{rp:>3d}/{total_rec} "
                       f"({rp * 100 // total_rec:>2d}%)"
                       if total_rec else "  -")
            print(f"  {cid:25s} {sc:6s} {n:>4d} "
                  f"{strict:>3d}/{n} ({strict * 100 // n:>2d}%) "
                  f"{rec_str:>12s}  {unrec:>5d}")

            if r["fail_reasons"]:
                top = r["fail_reasons"].most_common(1)[0]
                print(f"    top fail: [{top[1]}x] {top[0]}")
        print()

    total_strict = sum(sum(r["strict"]) for r in results.values())
    total_rp = sum(r["recovered_pass"] for r in results.values())
    total_rec = sum(
        r["recovered_pass"] + r["recovered_fail"]
        for r in results.values()
    )
    total_n = sum(len(r["strict"]) for r in results.values())
    print(f"SUMMARY: strict={total_strict}/{total_n} "
          f"({total_strict * 100 // total_n}%)  "
          f"recovered_pass={total_rp}/{total_rec} "
          f"({total_rp * 100 // total_rec if total_rec else 0}%)")


if __name__ == "__main__":
    main()
