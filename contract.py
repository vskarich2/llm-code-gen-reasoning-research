"""Contract-Gated Execution (CGE) — contract schema, parsing, prompt builders.

A contract is a JSON object the model emits BEFORE code generation,
declaring what it will change, what it must preserve, and what
behavioral effects the fix must achieve.
"""

import json
import logging
import re

log = logging.getLogger("t3.contract")

# ============================================================
# CLOSED VOCABULARY — only these effects are verifiable in v1
# ============================================================

ALLOWED_EFFECTS = frozenset({
    "introduce_idempotency_guard",
    "prevent_duplicate_effect",
    "add_rollback_on_failure",
    "preserve_effect_order",
    "guard_side_effect",
    "defer_side_effect_until_success",
})

CONTRACT_SCHEMA_TEXT = """{
  "root_cause": "string — what the actual bug/issue is",
  "must_change": ["file::function_name — functions that MUST be modified"],
  "must_not_change": ["file::function_name — functions that MUST NOT be modified"],
  "required_effects": ["from this list ONLY: """ + ", ".join(sorted(ALLOWED_EFFECTS)) + """],
  "side_effects": [
    {"effect": "function_name", "when": "before | after", "relative_to": "function_name"}
  ],
  "retry_semantics": {
    "idempotency_key_required": true/false,
    "duplicate_effects_forbidden": ["function names that must not be called twice"]
  },
  "rollback_semantics": {
    "must_rollback_if": ["condition descriptions"],
    "must_not_persist_after_failure": ["operation descriptions"]
  },
  "invariants": ["precise invariant statements"]
}"""


# ============================================================
# PARSING
# ============================================================

def parse_contract(raw: str) -> dict | None:
    """Parse a contract JSON from model output.

    Returns enriched contract dict with _unknown_effects,
    _unresolvable_orderings, _verifiable, _parse_error.
    Returns None if parsing fails entirely.
    """
    data = _extract_json(raw)
    if data is None:
        log.warning("SEVERE: could not parse contract from model output (len=%d)", len(raw))
        return None

    # Validate required fields
    for key in ("root_cause", "must_change", "must_not_change", "required_effects"):
        if key not in data:
            log.warning("Contract missing required field '%s'", key)
            data.setdefault(key, [] if key != "root_cause" else "")

    # Default optional fields
    data.setdefault("side_effects", [])
    data.setdefault("retry_semantics", {})
    data.setdefault("rollback_semantics", {})
    data.setdefault("invariants", [])

    # Validate required_effects against closed vocabulary
    known = []
    unknown = []
    for effect in data.get("required_effects", []):
        if effect in ALLOWED_EFFECTS:
            known.append(effect)
        else:
            unknown.append(effect)
            log.warning("Unknown required_effect '%s' — not verifiable", effect)
    data["required_effects"] = known
    data["_unknown_effects"] = unknown

    # Validate side_effects structure
    unresolvable = []
    valid_side_effects = []
    for se in data.get("side_effects", []):
        if not isinstance(se, dict):
            unresolvable.append(str(se))
            continue
        if "effect" not in se or "when" not in se or "relative_to" not in se:
            unresolvable.append(f"malformed: {se}")
            continue
        if se["when"] not in ("before", "after"):
            unresolvable.append(f"invalid 'when'={se['when']} for effect={se.get('effect')}")
            continue
        valid_side_effects.append(se)
    data["side_effects"] = valid_side_effects
    data["_unresolvable_orderings"] = unresolvable

    # Compute verifiable
    data["_verifiable"] = (
        len(unknown) == 0
        and len(unresolvable) == 0
        and bool(data.get("root_cause"))
        and isinstance(data.get("must_change"), list)
        and isinstance(data.get("required_effects"), list)
    )
    data["_parse_error"] = None

    return data


def _extract_json(raw: str) -> dict | None:
    """Try multiple strategies to extract a JSON object from raw text."""
    # Try 1: direct parse
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d
    except (json.JSONDecodeError, TypeError):
        pass

    # Try 2: ```json code block
    m = re.search(r"```json\s*\n(.*?)```", raw, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            pass

    # Try 3: outermost {...}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group())
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# PROMPT BUILDERS
# ============================================================

def build_contract_prompt(task: str, code_files: dict[str, str]) -> str:
    """Prompt to elicit the contract (Step 1)."""
    from prompts import _format_code_files
    file_block = _format_code_files(code_files)
    return f"""{task}

{file_block}

Before writing any code, analyze this codebase and identify the causal dependencies.

Produce an Execution Contract as JSON with this exact schema:

{CONTRACT_SCHEMA_TEXT}

Return ONLY the JSON contract. Do not write code yet."""


def build_code_from_contract_prompt(task: str, code_files: dict[str, str],
                                     contract: dict) -> str:
    """Prompt to generate code conditioned on the contract (Step 2)."""
    from prompts import _format_code_files
    file_block = _format_code_files(code_files)
    contract_json = json.dumps(contract, indent=2, default=str)
    return f"""{task}

{file_block}

You committed to this Execution Contract:

{contract_json}

Write refactored code that satisfies ALL contract terms. Specifically:
- Modify ONLY the functions listed in must_change
- Do NOT modify functions listed in must_not_change
- Implement ALL required_effects
- Maintain ALL invariants
- Respect the ordering, retry, and rollback constraints

Return the code only."""


def build_retry_prompt(task: str, code_files: dict[str, str],
                       contract: dict, violations: list[str]) -> str:
    """Prompt for retry after gate violations (Step 4)."""
    from prompts import _format_code_files
    file_block = _format_code_files(code_files)
    contract_json = json.dumps(contract, indent=2, default=str)
    v_text = "\n".join(f"  - {v}" for v in violations)
    return f"""{task}

{file_block}

Your code violates the Execution Contract you committed to.

VIOLATIONS:
{v_text}

Your original contract:
{contract_json}

Fix EACH violation specifically. Do not change anything else.
Return corrected code only."""
