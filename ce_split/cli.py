import sys
from .core import run_task
from .files import get_default_files

def main():
    if len(sys.argv) < 2:
        print("Usage: ce 'task'")
        return

    task = sys.argv[1]
    files = get_default_files()

    run_task(task, files, {"mode": "direct"})

if __name__ == "__main__":
    main()
