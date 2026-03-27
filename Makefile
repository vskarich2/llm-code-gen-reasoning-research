.PHONY: format lint typecheck semgrep arch deadcode test all check

# 1. Format (black)
format:
	.venv/bin/black .

# 2. Lint (ruff — sole linter + import sorter, no flake8/isort)
lint:
	.venv/bin/ruff check .

# 3. Typecheck (pyright primary, mypy secondary)
typecheck:
	.venv/bin/pyright
	.venv/bin/mypy runner.py execution.py evaluator.py exec_eval.py parse.py reconstructor.py llm.py live_metrics.py

# 4. Semgrep invariant enforcement
semgrep:
	semgrep scan --config .semgrep.yml --error --exclude='.venv' --exclude='code_snippets_v2' --exclude='_archive' --exclude='tests' .

# 5. Architecture constraint enforcement
arch:
	.venv/bin/lint-imports

# 6. Dead code detection
deadcode:
	.venv/bin/vulture runner.py execution.py evaluator.py exec_eval.py parse.py reconstructor.py llm.py live_metrics.py experiment_config.py constants.py failure_classifier.py --min-confidence 80

# 7. Tests
test:
	.venv/bin/pytest tests/ -v --tb=short

# Quick check (no typecheck, no deadcode, no tests)
check: lint semgrep arch

# Full suite — strict order: format → lint → typecheck → semgrep → arch → deadcode → test
# Each step must pass before the next runs (make stops on first failure)
all:
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) semgrep
	$(MAKE) arch
	$(MAKE) deadcode
	$(MAKE) test
