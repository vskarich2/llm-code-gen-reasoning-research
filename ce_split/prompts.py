import json
from pathlib import Path

def build_prompt(task: str, files: str) -> str:
    return f"""
You are a code modification engine.

STRICT:
- Output ONLY a valid unified diff
- No explanation
- Must apply with git apply

TASK:
{task}

FILES:
{files}
"""

def build_eval_prompt(task: str, diff: str) -> str:
    return f"""
You are a strict evaluator.

Return ONLY valid JSON.

Schema:
{{
  "task_correct": true/false,
  "suspicious": true/false,
  "reason": "<short explanation>"
}}

TASK:
{task}

DIFF:
{diff}
"""

def build_prompt_with_feedback(task: str, files: str, failure_context):
    try:
        rules = Path("CLAUDE_RULES/ENTRYPOINT.md").read_text()
    except Exception:
        rules = "ERROR: CLAUDE_RULES/ENTRYPOINT.md not found"

    base = f"""
You are a code modification engine.

CRITICAL: You MUST read and follow ALL rules below before making any change.

===== CLAUDE RULES =====
{rules}
===== END RULES =====

STRICT:
- FIRST output JSON: {{"files": ["file1.py"]}}
- THEN output diff
- No explanations

TASK:
{task}

FILES:
{files}
"""

    if not failure_context:
        return base

    return base + f"""

FAILURE:
{json.dumps(failure_context, indent=2)}
"""
