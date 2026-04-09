.PHONY: format lint typecheck semgrep arch deadcode test all check

# Use virtual environment binaries consistently
VENV_BIN := .venv/bin

# 1. Format (black)
format:
	$(VENV_BIN)/black .

# 2. Lint (ruff — sole linter + import sorter)
lint:
	$(VENV_BIN)/ruff check .

# 3. Typecheck (full project coverage)
typecheck:
	$(VENV_BIN)/pyright
	$(VENV_BIN)/mypy .

# 4. Semgrep invariant enforcement (use venv, full repo)
semgrep:
	$(VENV_BIN)/semgrep scan --config .semgrep.yml \
		--error \
		--exclude='.venv' \
		--exclude='code_snippets_v2' \
		--exclude='_archive' \
		--exclude='tests' \
		.

# 5. Architecture constraint enforcement
arch:
	$(VENV_BIN)/lint-imports

# 6. Dead code detection (full repo)
deadcode:
	$(VENV_BIN)/vulture . --min-confidence 80

# 7. Tests
test:
	$(VENV_BIN)/pytest tests/ -v --tb=short

# Quick check (fast feedback loop)
check: lint semgrep arch

# Full suite — strict ordered pipeline
all:
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) semgrep
	$(MAKE) arch
	$(MAKE) deadcode
	$(MAKE) test