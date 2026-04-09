import uuid
from .utils import run, run_capture

def ensure_clean():
    if run_capture("git status --porcelain"):
        raise RuntimeError("Repo not clean")

def create_branch():
    branch = f"claude/{uuid.uuid4().hex[:8]}"
    run(f"git checkout -b {branch}")
    return branch

def commit_push(branch: str, message: str):
    run("git add .")
    run(f'git commit -m "{message}"')
    run(f"git push origin {branch}")
    run(f"gh pr create --fill --head {branch}")
