import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "case_data" / "deep_dependency_chain_cases"
CASES_DIR = ROOT / "cases"
COMPILER_FILE = ROOT / "compiler" / "case_compiler.py"

def main():
    if not CASES_DIR.exists():
        raise RuntimeError(f"Cases directory not found: {CASES_DIR}")

    case_files = [
        f for f in CASES_DIR.glob("case_*.py")
        if f.is_file() and f.name != "__init__.py"
    ]

    for case_file in case_files:
        case_name = case_file.stem.replace("case_", "")
        case_root = ROOT / case_name

        # Create directory structure
        (case_root / "cases").mkdir(parents=True, exist_ok=True)
        (case_root / "compiler").mkdir(parents=True, exist_ok=True)
        (case_root / "generated_cases").mkdir(parents=True, exist_ok=True)

        # Move case file
        target_case_path = case_root / "cases" / case_file.name
        shutil.move(str(case_file), str(target_case_path))

        # Copy compiler
        if COMPILER_FILE.exists():
            target_compiler_path = case_root / "compiler" / "case_compiler.py"
            shutil.copy(str(COMPILER_FILE), str(target_compiler_path))

        print(f"Set up case: {case_name}")

    # Optional: remove empty original cases dir (except __init__.py)
    remaining = list(CASES_DIR.glob("*"))
    if all(f.name == "__init__.py" for f in remaining):
        print("Leaving __init__.py in original cases directory")
    else:
        print("Warning: some files remain in original cases directory")

if __name__ == "__main__":
    main()