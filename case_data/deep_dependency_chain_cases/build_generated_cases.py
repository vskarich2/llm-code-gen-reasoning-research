"""Driver helpers for compiling generated deep dependency chain cases."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from case_data.deep_dependency_chain_cases.compiler import compile_single_case


if __name__ == "__main__":
    compile_single_case("ml_feature")
    compile_single_case("logging_pipeline")
