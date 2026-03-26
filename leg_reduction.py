"""LEG-Reduction Pipeline — auditable intra-call self-correction.

Forces the model to expose each internal iteration as a structured revision
record with causal links: issue → invariant → verification → change → code.

Output schema (strict, all fields mandatory):
{
  "bug_diagnosis": str,
  "plan_steps": [{"step": str, "intended_effect": str}],
  "revision_history": [
    {
      "revision": int,
      "verification": [{"step": str, "status": "PASS"|"FAIL", "evidence": str}],
      "invariants_checked": [{"invariant": str, "status": "PASS"|"FAIL", "evidence": str}],
      "issues_found": [{"issue_id": str, "description": str, "evidence": str, "related_invariant": str|null}],
      "changes_made": [{"change_type": "add"|"modify"|"delete", "target": str, "description": str}] | null,
      "changed_functions": [str],
      "code_before": str,
      "code_after": str
    }
  ],
  "verification": [...],        # MUST equal revision_history[-1].verification
  "code": str,                  # MUST equal revision_history[-1].code_after
  "internal_revisions": int     # MUST equal len(revision_history) - 1
}
"""

import json
import logging
import re

_log = logging.getLogger("t3.leg_reduction")

MAX_INTERNAL_REVISIONS = 3

_VALID_STATUSES = frozenset(["PASS", "FAIL"])
_VALID_CHANGE_TYPES = frozenset(["add", "modify", "delete"])


# ============================================================
# PROMPT
# ============================================================

def build_leg_reduction_prompt(task: str, code_files: dict[str, str]) -> str:
    """Build the LEG-reduction prompt with full revision trace schema."""
    from prompts import _format_code_files
    file_block = _format_code_files(code_files)

    return f"""{task}

{file_block}

You MUST respond with a SINGLE valid JSON object. No text outside the JSON.
No markdown fences. Follow this EXACT schema:

{{
  "bug_diagnosis": "<one sentence: root cause>",
  "plan_steps": [
    {{"step": "<what to change>", "intended_effect": "<what this achieves>"}}
  ],
  "revision_history": [
    {{
      "revision": 0,
      "verification": [
        {{"step": "<plan step text>", "status": "PASS" or "FAIL", "evidence": "<concrete code reference>"}}
      ],
      "invariants_checked": [
        {{"invariant": "<invariant statement>", "status": "PASS" or "FAIL", "evidence": "<concrete evidence>"}}
      ],
      "issues_found": [
        {{"issue_id": "ISS-1", "description": "<what is wrong>", "evidence": "<code reference>", "related_invariant": "<invariant text or null>"}}
      ],
      "changes_made": null,
      "changed_functions": [],
      "code_before": "<the original buggy code>",
      "code_after": "<your fixed code after this revision>"
    }}
  ],
  "verification": [<MUST be identical to revision_history[-1].verification>],
  "code": "<MUST be identical to revision_history[-1].code_after>",
  "internal_revisions": <MUST equal len(revision_history) - 1>
}}

PROCEDURE — follow IN ORDER:

STEP 1: DIAGNOSE
Identify the root cause. Write "bug_diagnosis".

STEP 2: PLAN
List atomic code changes in "plan_steps". Each step = one change.

STEP 3: REVISION 0 — Initial attempt
- Set "code_before" to the original buggy code
- Write your fixed code in "code_after"
- For EACH plan step: check if implemented. Record in "verification" with status PASS/FAIL and concrete evidence referencing your code.
- For EACH invariant you identified: check if it holds. Record in "invariants_checked" with PASS/FAIL and evidence.
- If any verification or invariant is FAIL: record in "issues_found" with issue_id, description, evidence, and related_invariant.
- Set "changes_made" to null (this is revision 0).
- Set "changed_functions" to [] (this is revision 0).

STEP 4: SELF-CORRECT (if needed)
If revision 0 has ANY verification FAIL or invariant FAIL:
- Create revision 1:
  - Set "code_before" to the previous revision's "code_after"
  - Fix the issues
  - Set "code_after" to your revised code
  - "changes_made": list each change with change_type (add/modify/delete), target function, description
  - "changed_functions": list every function you modified
  - Re-verify ALL steps and invariants
  - If new issues: record them in "issues_found"
- Repeat for revision 2, 3 if needed (max {MAX_INTERNAL_REVISIONS} revisions)

STEP 5: FINALIZE
- "verification" (top-level) = revision_history[-1].verification (copy it exactly)
- "code" (top-level) = revision_history[-1].code_after (copy it exactly)
- "internal_revisions" = len(revision_history) - 1

RULES:
- Every revision MUST have ALL fields. No optional fields.
- verification[].status MUST be "PASS" or "FAIL" (not true/false)
- invariants_checked[].status MUST be "PASS" or "FAIL"
- changes_made[].change_type MUST be "add", "modify", or "delete"
- Revision 0 MUST have changes_made = null and changed_functions = []
- If you revise, every change MUST correspond to a previously identified issue
- Do NOT make changes without a prior issue
- Do NOT report issues without verification or invariant failures
- code_before and code_after MUST be actual code strings, not placeholders
- Return ONLY the JSON object. No other text."""


# ============================================================
# JSON EXTRACTION (reused from old version)
# ============================================================

def _extract_json(raw: str) -> str | None:
    """Extract first balanced JSON object from raw text."""
    text = raw.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# ============================================================
# VALIDATION HELPERS
# ============================================================

def _extraction_fail(msg: str) -> dict:
    """Return a result for TRUE code extraction failure.

    parse_error is set because no code could be extracted.
    code_extracted=False. This blocks execution.
    """
    return {
        "parse_error": msg,
        "valid": False,
        "code_extracted": False,
        "schema_compliant": False,
        "schema_violations": [msg],
        "extraction_source": None,
        "bug_diagnosis": "",
        "plan_steps": [],
        "revision_history": [],
        "verification": [],
        "code": "",
        "internal_revisions": 0,
        "all_steps_verified": None,
        "leg_reduction_exceeded_max_revisions": False,
        "validation_errors": [msg],
    }


def _fail(msg: str) -> dict:
    """Legacy wrapper — routes to _extraction_fail."""
    return _extraction_fail(msg)


def _validate_verification_entry(v, idx, prefix):
    """Validate a single verification entry. Returns error string or None."""
    if not isinstance(v, dict):
        return f"{prefix}verification[{idx}]: not a dict"
    for key in ("step", "status", "evidence"):
        if key not in v:
            return f"{prefix}verification[{idx}]: missing '{key}'"
    if not isinstance(v["step"], str) or not v["step"].strip():
        return f"{prefix}verification[{idx}].step: must be non-empty string"
    if v["status"] not in _VALID_STATUSES:
        return f"{prefix}verification[{idx}].status: must be PASS or FAIL, got {v['status']!r}"
    if not isinstance(v["evidence"], str):
        return f"{prefix}verification[{idx}].evidence: must be string"
    return None


def _validate_invariant_entry(inv, idx, prefix):
    """Validate a single invariants_checked entry."""
    if not isinstance(inv, dict):
        return f"{prefix}invariants_checked[{idx}]: not a dict"
    for key in ("invariant", "status", "evidence"):
        if key not in inv:
            return f"{prefix}invariants_checked[{idx}]: missing '{key}'"
    if not isinstance(inv["invariant"], str) or not inv["invariant"].strip():
        return f"{prefix}invariants_checked[{idx}].invariant: must be non-empty string"
    if inv["status"] not in _VALID_STATUSES:
        return f"{prefix}invariants_checked[{idx}].status: must be PASS or FAIL, got {inv['status']!r}"
    if not isinstance(inv["evidence"], str):
        return f"{prefix}invariants_checked[{idx}].evidence: must be string"
    return None


def _validate_issue_entry(iss, idx, prefix):
    """Validate a single issues_found entry."""
    if not isinstance(iss, dict):
        return f"{prefix}issues_found[{idx}]: not a dict"
    for key in ("issue_id", "description", "evidence"):
        if key not in iss:
            return f"{prefix}issues_found[{idx}]: missing '{key}'"
    if "related_invariant" not in iss:
        return f"{prefix}issues_found[{idx}]: missing 'related_invariant'"
    if not isinstance(iss["issue_id"], str):
        return f"{prefix}issues_found[{idx}].issue_id: must be string"
    if not isinstance(iss["description"], str):
        return f"{prefix}issues_found[{idx}].description: must be string"
    return None


def _validate_change_entry(ch, idx, prefix):
    """Validate a single changes_made entry."""
    if not isinstance(ch, dict):
        return f"{prefix}changes_made[{idx}]: not a dict"
    for key in ("change_type", "target", "description"):
        if key not in ch:
            return f"{prefix}changes_made[{idx}]: missing '{key}'"
    if ch["change_type"] not in _VALID_CHANGE_TYPES:
        return f"{prefix}changes_made[{idx}].change_type: must be add/modify/delete, got {ch['change_type']!r}"
    if not isinstance(ch["target"], str):
        return f"{prefix}changes_made[{idx}].target: must be string"
    return None


# ============================================================
# MAIN PARSER
# ============================================================

def parse_leg_reduction_output(raw: str) -> dict:
    """Parse LEG-reduction response: extraction then validation.

    PHASE 1 — CODE EXTRACTION (never blocked by metadata):
    - Extract JSON, extract code field
    - If code is present and non-empty: code_extracted=True, parse_error=None
    - If code cannot be extracted: try restricted fallback
    - If fallback fails: code_extracted=False, parse_error set

    PHASE 2 — METADATA VALIDATION (informational, never blocks execution):
    - Validate revision_history, verification, consistency
    - Violations go to schema_violations, NOT parse_error
    - schema_compliant=True only if zero violations

    Returns dict with code, code_extracted, schema_compliant, schema_violations,
    extraction_source, and all LEG metadata fields.
    """
    if not raw or not raw.strip():
        return _extraction_fail("SEVERE: empty response")

    # ── PHASE 1: CODE EXTRACTION ──

    json_str = _extract_json(raw)
    json_extraction_failed = json_str is None

    parsed = None
    if not json_extraction_failed:
        try:
            parsed = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            json_extraction_failed = True

    if parsed is not None and not isinstance(parsed, dict):
        json_extraction_failed = True
        parsed = None

    # Extract code from JSON if available
    code = ""
    bug_diagnosis = ""
    extraction_source = "strict"

    if parsed is not None:
        raw_code = parsed.get("code")
        if isinstance(raw_code, str) and raw_code.strip():
            code = raw_code
        raw_diag = parsed.get("bug_diagnosis")
        if isinstance(raw_diag, str) and raw_diag.strip():
            bug_diagnosis = raw_diag

    # RESTRICTED FALLBACK: if JSON extraction failed or code field missing/empty
    if not code.strip():
        if json_extraction_failed or parsed is None or not parsed.get("code"):
            from parse import parse_model_response
            fallback = parse_model_response(raw)
            fallback_code = fallback.get("code") or ""
            if isinstance(fallback_code, str) and fallback_code.strip():
                code = fallback_code
                extraction_source = "fallback"
                _log.info("LEG restricted fallback recovered code (len=%d)", len(code))
                if not bug_diagnosis:
                    bug_diagnosis = fallback.get("reasoning") or ""

    # If still no code: hard extraction failure
    if not code.strip():
        return _extraction_fail(
            "no_json_object_found" if json_extraction_failed
            else "code must be non-empty string"
        )

    # Code extraction succeeded
    code_extracted = True

    # Extract remaining fields with safe defaults (metadata — optional)
    plan_steps = parsed.get("plan_steps", []) if parsed else []
    revision_history = parsed.get("revision_history", []) if parsed else []
    verification = parsed.get("verification", []) if parsed else []
    internal_revisions = parsed.get("internal_revisions", 0) if parsed else 0

    if not isinstance(plan_steps, list):
        plan_steps = []
    if not isinstance(revision_history, list):
        revision_history = []
    if not isinstance(verification, list):
        verification = []
    if not isinstance(internal_revisions, int):
        internal_revisions = 0

    # ── PHASE 2: METADATA VALIDATION (informational only) ──

    errors = []

    # Type/presence checks on metadata (record violations, never abort)
    if not isinstance(bug_diagnosis, str) or not bug_diagnosis.strip():
        errors.append("bug_diagnosis must be non-empty string")
    if len(plan_steps) == 0:
        errors.append("plan_steps is empty or missing")
    if len(revision_history) == 0:
        errors.append("revision_history is empty or missing")
    if len(verification) == 0:
        errors.append("verification is empty or missing")
    if internal_revisions < 0:
        errors.append(f"internal_revisions must be non-negative int, got {internal_revisions!r}")

    # --- Plan steps ---
    for i, step in enumerate(plan_steps):
        if not isinstance(step, dict):
            return _fail(f"plan_steps[{i}]: not a dict")
        for key in ("step", "intended_effect"):
            if key not in step:
                return _fail(f"plan_steps[{i}]: missing '{key}'")
            if not isinstance(step[key], str):
                return _fail(f"plan_steps[{i}].{key}: must be string")

    # --- Revision history validation ---
    # SOFT VALIDATION: all violations are recorded as errors[], never abort parse.
    # The code is still extracted from the last revision's code_after.
    # Violations are research signal (model's self-correction quality), not system errors.
    for ri, rev in enumerate(revision_history):
        prefix = f"revision_history[{ri}]."
        if not isinstance(rev, dict):
            errors.append(f"{prefix}not a dict — skipping")
            continue

        # Required fields — record missing, don't abort
        for key in ("revision", "verification", "invariants_checked",
                     "issues_found", "changes_made", "changed_functions",
                     "code_before", "code_after"):
            if key not in rev:
                errors.append(f"{prefix}missing '{key}'")

        # Revision index
        if rev.get("revision") != ri:
            errors.append(f"{prefix}revision={rev.get('revision')} but expected {ri}")

        # code_before / code_after type check
        if not isinstance(rev.get("code_before"), str):
            errors.append(f"{prefix}code_before: not a string")
        if not isinstance(rev.get("code_after"), str):
            errors.append(f"{prefix}code_after: not a string")

        # Verification entries
        rev_ver = rev.get("verification", [])
        if not isinstance(rev_ver, list):
            errors.append(f"{prefix}verification: not a list")
        else:
            for vi, v in enumerate(rev_ver):
                err = _validate_verification_entry(v, vi, prefix)
                if err:
                    errors.append(err)

        # Invariants entries
        rev_inv = rev.get("invariants_checked", [])
        if not isinstance(rev_inv, list):
            errors.append(f"{prefix}invariants_checked: not a list")
        else:
            for ii, inv in enumerate(rev_inv):
                err = _validate_invariant_entry(inv, ii, prefix)
                if err:
                    errors.append(err)

        # Issues entries
        rev_iss = rev.get("issues_found", [])
        if not isinstance(rev_iss, list):
            errors.append(f"{prefix}issues_found: not a list")
        else:
            for ii, iss in enumerate(rev_iss):
                err = _validate_issue_entry(iss, ii, prefix)
                if err:
                    errors.append(err)

        # changed_functions
        rev_cf = rev.get("changed_functions", [])
        if not isinstance(rev_cf, list):
            errors.append(f"{prefix}changed_functions: not a list")
        else:
            for ci, cf in enumerate(rev_cf):
                if not isinstance(cf, str):
                    errors.append(f"{prefix}changed_functions[{ci}]: not a string")

        # changes_made semantics
        changes = rev.get("changes_made")
        if ri == 0:
            if changes is not None:
                errors.append(f"{prefix}changes_made must be null for revision 0")
            if len(rev.get("changed_functions", [])) > 0:
                errors.append(f"{prefix}changed_functions must be [] for revision 0")
        else:
            if changes is None:
                errors.append(f"{prefix}changes_made must not be null for revision {ri}")
            elif isinstance(changes, list):
                for ci, ch in enumerate(changes):
                    err = _validate_change_entry(ch, ci, prefix)
                    if err:
                        errors.append(err)
            else:
                errors.append(f"{prefix}changes_made: must be list or null, got {type(changes).__name__}")

            # No-op detection
            cb = rev.get("code_before", "")
            ca = rev.get("code_after", "")
            if isinstance(cb, str) and isinstance(ca, str) and cb == ca:
                if not changes:
                    errors.append(f"{prefix}no-op revision: code_before == code_after with no changes_made")

            # Fake iteration detection
            if changes and isinstance(changes, list) and len(changes) > 0:
                if len(rev.get("issues_found", [])) == 0 and ri > 0:
                    prev_issues = revision_history[ri - 1].get("issues_found", [])
                    prev_fails = [v for v in revision_history[ri - 1].get("verification", [])
                                  if v.get("status") == "FAIL"]
                    if len(prev_issues) == 0 and len(prev_fails) == 0:
                        errors.append(
                            f"{prefix}unjustified changes: changes_made has entries "
                            f"but previous revision had no issues or failures"
                        )

    # --- Consistency checks (only if revision_history is non-empty) ---
    if not revision_history:
        errors.append("revision_history is empty — skipping consistency checks")
    else:
        # internal_revisions == len(revision_history) - 1
        expected_revisions = len(revision_history) - 1
        if internal_revisions != expected_revisions:
            errors.append(
                f"internal_revisions={internal_revisions} but revision_history has "
                f"{len(revision_history)} entries (expected {expected_revisions})"
            )

    # --- Consistency: top-level verification == last revision's verification ---
    last_rev_verification = revision_history[-1].get("verification", []) if revision_history else []
    if len(verification) != len(last_rev_verification):
        errors.append(
            f"top-level verification has {len(verification)} entries but "
            f"revision_history[-1].verification has {len(last_rev_verification)}"
        )
    else:
        for vi in range(len(verification)):
            tv = verification[vi]
            lv = last_rev_verification[vi]
            # Convert old-schema top-level verification to match if needed
            tv_step = tv.get("step", "")
            lv_step = lv.get("step", "")
            tv_status = tv.get("status", tv.get("implemented"))
            lv_status = lv.get("status", "")
            if tv_step != lv_step:
                errors.append(
                    f"verification[{vi}].step mismatch: top-level={tv_step!r} vs last_rev={lv_step!r}"
                )
                break

    # --- Top-level code == last revision code_after ---
    last_code_after = revision_history[-1].get("code_after", "") if revision_history else ""
    if revision_history and code.strip() != last_code_after.strip():
        errors.append(
            "top-level code does not match revision_history[-1].code_after"
        )

    # --- If multiple revisions, revision 0 must have had failures ---
    if len(revision_history) > 1:
        rev0 = revision_history[0]
        rev0_fails = [v for v in rev0.get("verification", []) if v.get("status") == "FAIL"]
        rev0_inv_fails = [i for i in rev0.get("invariants_checked", []) if i.get("status") == "FAIL"]
        rev0_issues = rev0.get("issues_found", [])
        if not rev0_fails and not rev0_inv_fails and not rev0_issues:
            errors.append(
                "revision_history has >1 entries but revision 0 has no failures or issues "
                "(self-correction without initial failure is incoherent)"
            )

    # --- Top-level verification entry structure check ---
    for vi, v in enumerate(verification):
        err = _validate_verification_entry(v, vi, "top-level ")
        if err:
            errors.append(err)

    # --- Compute derived fields ---
    all_verified = all(v.get("status") == "PASS" for v in verification)
    exceeded = internal_revisions > MAX_INTERNAL_REVISIONS

    # Violations as structured data (research signal, not system errors)
    violations = [{"type": "validation", "description": e, "revision": None} for e in errors]
    # Max possible: ~15 checks per revision × num_revisions + ~5 consistency checks
    max_possible = max(15 * len(revision_history) + 5, 1)
    validity_score = round(1.0 - (len(violations) / max_possible), 3)

    result = {
        # PHASE 1 result: code extraction
        "parse_error": None,               # None because code WAS extracted
        "code_extracted": code_extracted,
        "extraction_source": extraction_source,
        # PHASE 2 result: metadata validation
        "valid": len(errors) == 0,
        "schema_compliant": len(errors) == 0,
        "schema_violations": errors,
        "validation_errors": errors,       # backward compat alias
        "violations": violations,
        "validity_score": validity_score,
        # Extracted fields
        "bug_diagnosis": bug_diagnosis,
        "plan_steps": plan_steps,
        "revision_history": revision_history,
        "verification": verification,
        "code": code,
        "internal_revisions": internal_revisions,
        "all_steps_verified": all_verified,
        "leg_reduction_exceeded_max_revisions": exceeded,
    }

    if errors:
        # Metadata errors go to schema_violations, NOT parse_error.
        # parse_error stays None because code extraction succeeded.
        _log.info("LEG-reduction schema violations (%d, validity=%.2f): %s",
                  len(errors), validity_score, errors[:3])

    if not all_verified:
        unimplemented = [v for v in verification if v.get("status") == "FAIL"]
        _log.warning(
            "LEG-reduction: %d/%d steps FAIL after %d revisions",
            len(unimplemented), len(verification), internal_revisions
        )

    if exceeded:
        _log.warning(
            "LEG-reduction: exceeded max revisions (%d > %d)",
            internal_revisions, MAX_INTERNAL_REVISIONS
        )

    return result
