from typing import List, Dict, Optional
from .git_ops import ensure_clean, create_branch, commit_push
from .validation import validate_diff, apply_patch, validate_code
from .files import read_files
from .llm import call_model
from .evaluate import evaluate
from .wal import log_event
from .prompts import build_prompt_with_feedback

def run_task(task: str, files: List[str], metadata: Dict, dry_run: bool = False):
    ensure_clean()
    file_content = read_files(files)

    prompt = build_prompt_with_feedback(task, file_content, None)
    diff = call_model(prompt)

    validate_diff(diff)

    if dry_run:
        print(diff)
        return

    apply_patch(diff)
    validate_code()

    eval_result = evaluate(task, diff)

    if not eval_result["task_correct"]:
        raise RuntimeError("Evaluation failed")

    branch = create_branch()
    commit_push(branch, task)

    log_event({"type": "success", "task": task})
