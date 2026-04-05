#!/usr/bin/env python3
"""Load the next case file into the macOS clipboard (pbcopy).

Reads queue.yaml to find the first file marked true, loads its contents
into the clipboard, then marks it false. Run again to get the next one.

To redo a file, edit queue.yaml and set it back to true.

Usage:
    python load_next.py          # load next file into clipboard
    python load_next.py --reset  # reset all to true
    python load_next.py --status # show which are done/pending
"""

import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent
QUEUE_PATH = SCRIPT_DIR / "queue.yaml"


def load_queue():
    return yaml.safe_load(QUEUE_PATH.read_text())


def save_queue(queue):
    lines = []
    for name, val in queue.items():
        lines.append(f"{name}: {'true' if val else 'false'}")
    QUEUE_PATH.write_text("\n".join(lines) + "\n")


def pbcopy(text):
    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    proc.communicate(text.encode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError("pbcopy failed")


def cmd_status(queue):
    pending = [n for n, v in queue.items() if v]
    done = [n for n, v in queue.items() if not v]
    print(f"Pending: {len(pending)}")
    for n in pending:
        print(f"  [ ] {n}")
    print(f"Done: {len(done)}")
    for n in done:
        print(f"  [x] {n}")


def cmd_reset(queue):
    for name in queue:
        queue[name] = True
    save_queue(queue)
    print(f"Reset all {len(queue)} files to true.")


def cmd_load_next(queue):
    # Find first true entry
    target = None
    for name, val in queue.items():
        if val:
            target = name
            break

    if target is None:
        print("All files have been loaded. Run with --reset to start over.")
        return

    # Load file contents
    file_path = SCRIPT_DIR / target
    if not file_path.exists():
        print(f"ERROR: {file_path} does not exist")
        sys.exit(1)

    content = file_path.read_text()
    pbcopy(content)

    # Mark as done
    queue[target] = False
    save_queue(queue)

    # Count remaining
    remaining = sum(1 for v in queue.values() if v)
    print(f"Loaded: {target} ({len(content):,} chars) -> clipboard")
    print(f"Remaining: {remaining}/{len(queue)}")


def main():
    queue = load_queue()

    if "--reset" in sys.argv:
        cmd_reset(queue)
    elif "--status" in sys.argv:
        cmd_status(queue)
    else:
        cmd_load_next(queue)


if __name__ == "__main__":
    main()
