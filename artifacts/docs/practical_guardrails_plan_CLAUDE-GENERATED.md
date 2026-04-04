# Plan: Practical Guardrails for T3 Benchmark Repo

**Date:** 2026-03-23
**Status:** PLAN ONLY — awaiting approval

## Context

The T3 benchmark repo has almost no code quality tooling — just pytest and a minimal GitHub Actions workflow that runs tests only. No linting, no type checking, no formatting, no pre-commit hooks, no CLAUDE.md. This is a research codebase where silent bugs can invalidate experiments. The report identifies high-impact, low-overhead guardrails we can add.

**Prioritization principle:** This is a research repo, not a production app. We want guardrails that prevent *silent experiment corruption* (the highest-stakes failure), not enterprise compliance. Skip dependency scanning, container scanning, and heavy SAST. Focus on: catching broken code fast, enforcing conventions, and making Claude Code sessions more reliable.

---

## What Already Exists

| Item | Status | Location |
|---|---|---|
| pytest | Configured | `pyproject.toml` (markers, testpaths) |
| GitHub Actions CI | Minimal (tests only) | `.github/workflows/tests.yaml` |
| .claude/SYSTEM.md | Exists (governance doc) | `.claude/SYSTEM.md` |
| .claude/settings.local.json | Exists (permissions) | `.claude/settings.local.json` |
| CLAUDE.md | **Missing** | — |
| Pre-commit | **Missing** | — |
| Ruff | **Missing** | — |
| Mypy/type checking | **Missing** | — |
| Formatter | **Missing** | — |

---

## What To Add (Priority Order)

### Tier 1: High Impact, Zero Friction

#### 1. CLAUDE.md at T3_code_generation_MVP root

This is the single highest-leverage addition per the research report. Claude Code loads this every session. Encodes:
- Project commands (test, lint)
- Patch rules (minimal diffs, don't refactor unrelated code)
- Convention enforcement
- Key file locations

#### 2. Ruff (linter + formatter)

Fast, catches complexity creep, bad patterns, and formatting drift. Replaces flake8 + black + isort. PLR0915 (too-many-statements) catches "LLM wrote a giant function" as a deterministic CI failure.

#### 3. Pre-commit hooks

Minimal — just ruff. No heavy tools. Catches formatting and lint issues before commit.

### Tier 2: Moderate Impact, Low Friction

#### 4. Semgrep custom rules for silent-failure patterns

Two rules: bare-except and catch-exception-pass. These catch exception swallowing that hides test failures.

#### 5. Enhanced CI workflow

Add ruff check + format check to GitHub Actions. Makes lint violations block PRs.

### Tier 3: Nice-to-Have

#### 6. detect-secrets baseline
#### 7. Mypy — Skip for now (too many dict returns, not actionable)

---

## What NOT To Add

CodeQL, pip-audit, OSV-Scanner, Trivy, mutmut, Hypothesis, black, pylint, flake8 — all either overkill for a research repo or replaced by ruff.

---

## Files to Create/Modify

| File | Action |
|---|---|
| `T3_code_generation_MVP/CLAUDE.md` | **CREATE** |
| `pyproject.toml` | **MODIFY** (add ruff config) |
| `.pre-commit-config.yaml` | **CREATE** |
| `semgrep.yml` | **CREATE** |
| `.github/workflows/tests.yaml` | **MODIFY** |
| `.gitignore` | **MODIFY** |

---

## Implementation Order

1. Create CLAUDE.md
2. Add ruff config to pyproject.toml
3. Fix blocking ruff violations or configure ignores
4. Create .pre-commit-config.yaml
5. Create semgrep.yml
6. Update CI workflow
7. Run full test suite
