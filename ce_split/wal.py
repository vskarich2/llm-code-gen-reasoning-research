import json
from datetime import datetime
from pathlib import Path
from .config import WAL_PATH

def log_event(event: dict):
    WAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    event["timestamp"] = datetime.utcnow().isoformat()
    with open(WAL_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")
