from pathlib import Path

FORBIDDEN_PATTERNS = [r"\.env", r"secret", r"token", r"api_key"]
MAX_ATTEMPTS = 3
MODEL = "gpt-5"
WAL_PATH = Path("runs/wal.jsonl")
LAST_RUN_PATH = Path(".ce_last.json")
