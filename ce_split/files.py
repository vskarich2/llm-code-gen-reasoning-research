from pathlib import Path
from typing import List
from .utils import run_capture

def read_files(paths: List[str]) -> str:
    content = []
    for p in paths:
        try:
            content.append(f"FILE: {p}\n{Path(p).read_text()}\n")
        except:
            pass
    return "\n".join(content)

def get_default_files(limit=5):
    return run_capture("git ls-files").splitlines()[:limit]
