import json
from .llm import call_model
from .prompts import build_eval_prompt

def evaluate(task: str, diff: str):
    raw = call_model(build_eval_prompt(task, diff))
    try:
        return json.loads(raw)
    except:
        return {"task_correct": False, "suspicious": True, "reason": "invalid_json"}
