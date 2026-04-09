# Practical Mitigations for LLM Code-Generation Failures in Claude Code Workflows

## Executive summary

**Snapshot date:** 2026-03-23 (America/New_York).

**Concise research plan (executed):**
- Identify the most-used **public GitHub prompt repositories** you specified (and a small set of adjacent high-signal repos) and extract **code-gen / patch / edit / review** prompt templates (verbatim when short, otherwise normalized templates with provenance). citeturn10view0turn16view0turn7view4turn7view3turn17view1turn16view1turn24view1  
- Prioritize **Claude Code workflows** and official guidance: **CLAUDE.md**, Plan/Explore/Implement loops, and “verification-first” practices; extract concrete prompts and guardrails described publicly. citeturn9view1turn8view2turn9view0turn7view0  
- Inventory a **practical programmatic check stack** (Python-first): formatter/linter/type checker, AST rule engines (Semgrep), CodeQL, tests + property-based + mutation testing, secret/dependency scanning, and CI patterns. citeturn21search4turn6search0turn6search1turn21search7turn4search0turn4search1turn6search2turn4search2turn4search3  
- Synthesize an **actionable mapping** from known failure modes → prompt interventions → programmatic checks → residual risks & tradeoffs, and translate into a **starter pack** for a Claude Code-based patch workflow and for your causal audit. citeturn9view1turn9view0turn15view1turn3search9turn6search19  

**What big teams and experienced developers do in practice (the throughline):**
- They reduce “silent semantic failure” by making the model **self-verifying** (tests/expected outputs/commands) and by routing work through **structured phases** (Explore → Plan → Implement → Verify → PR). Anthropic’s Claude Code best practices explicitly say verification criteria are the “single highest-leverage” improvement and warn that without success criteria you become “the only feedback loop.” citeturn9view1  
- They constrain scope to avoid “helpful overreach”: Claude’s official prompting guide recommends explicit instructions to **avoid overengineering**, **avoid test-hardcoding**, and **read the code before making claims**. These map directly to failure modes like wrong-problem mapping, brittle implementations, and hallucinated APIs. citeturn9view0  
- They standardize project guidance for agents via persistent instruction files (Claude Code’s **CLAUDE.md**, GitHub Copilot’s **.github/copilot-instructions.md**, OpenAI Codex’s **AGENTS.md**, and the cross-tool AGENTS.md initiative). This turns “prompting” into maintainable configuration, and critically enables **controlled interventions** for your causal audit. citeturn8view2turn25view3turn25view4turn25view5  
- They treat “mitigation tooling” itself as part of the threat model: recent disclosures show CI actions can be compromised; pinning and least-privilege are now part of best practice when you add security scans to agent workflows. citeturn25view6  

## Prompt repositories and curated code prompts

### Curated inventory of prompt repositories

Below is a **high-signal “top ~10”** list emphasizing your constraints: GitHub-hosted prompt repos, Claude Code relevance, and actionable developer prompts. URLs are provided explicitly.

| Repo / collection | What it’s best for | Notes on provenance | URL |
|---|---|---|---|
| **prompts.chat dataset (Awesome ChatGPT Prompts)** | Large, community prompt catalog; includes multiple “Code Reviewer” and code quality prompts | Community-contributed prompts; quality varies widely | https://github.com/f/prompts.chat citeturn7view5turn10view0 |
| **Prompt Engineering Guide (DAIR.AI)** | Patterns and example prompts, including code generation & editing examples | Educational guide; code “applications” section exists but notes parts “under development” | https://github.com/dair-ai/Prompt-Engineering-Guide and https://www.promptingguide.ai/applications/coding citeturn16view1turn24view1 |
| **The Big Prompt Library** | Large collection of system prompts/custom instructions across tools | Explicitly includes system prompts and also jailbreak-related content; use cautiously as “learning,” not as authoritative vendor policy | https://github.com/0xeb/TheBigPromptLibrary citeturn16view0turn16view0 |
| **Claude Code system prompts (Piebald-AI)** | Up-to-date extracted system/subagent prompts for Claude Code, including verification specialist and plan mode | Claims extraction from compiled Claude Code releases; best used to understand Claude Code’s built-in guardrails | https://github.com/Piebald-AI/claude-code-system-prompts citeturn7view3turn14view0turn15view1 |
| **Awesome Reviewers** | Large registry of code review system prompts; includes export to Claude Skills | Claims 8K+ curated prompts distilled from real PR review comments; practical but still prompt-based | https://github.com/baz-scm/awesome-reviewers citeturn7view4turn8view7 |
| **Awesome Claude Prompts** | General Claude prompt examples (mixed languages) | Not always English; content quality varies | https://github.com/langgptai/awesome-claude-prompts citeturn16view2 |
| **Continue prompt-file examples (archived)** | Small set of prompt-file examples (e.g., code review prompt referencing Google eng practices) | Archived repo, still useful as a “prompt file” format example | https://github.com/continuedev/prompt-file-examples citeturn17view1 |
| **Awesome Claude Skills** | Catalog of Claude “skills” (practical automation packages) | Acts more like an “operational prompt + tool wrapper” library | https://github.com/travisvn/awesome-claude-skills citeturn20search0 |
| **Claude skills mega-library** | Large library of Claude Code skills/plugins | Wide scope; treat as starting point for reusable workflows | https://github.com/alirezarezvani/claude-skills citeturn20search16 |
| **JeffreysPrompts.com repository** | “Battle-tested prompts for agentic coding,” including Claude Code | Market-style prompt registry; validate locally | https://github.com/Dicklesworthstone/jeffreysprompts.com citeturn16view3 |

### Curated prompt templates for code generation and patch/edit workflows

Because prompt repos vary in quality, this report focuses on **templates that explicitly mitigate known failure modes**: spec drift, overengineering, test-hardcoding, hallucinated APIs, and “looks right but doesn’t run.”

#### Normalization schema used below

Each template is presented as either:
- **Exact prompt text** when the original is short enough to quote safely, or
- A **normalized template** that preserves structure and the key constraints/verification instructions.

Each template is tagged by:
- Intended task: patch/edit/new code/refactor/review
- Constraints: minimal diff, no test edits, preserve API, no new files, etc.
- Verification: tests, linters, typecheck, command outputs, adversarial probes
- Failure modes targeted: spec misunderstanding, planning errors, local logic, API hallucination, environment/tooling, evaluation artifact (“passes tests but wrong”), security
- Provenance URL

#### Template inventory

**T1 — Claude Code “Give Claude a way to verify its work” (patch/edit/new code)**
- Intended task: patch/edit or new feature (general)
- Constraints: none inherent; encourages explicit success criteria
- Verification: include tests / screenshots / expected outputs; run tests after implementing
- Failure modes targeted: silent wrong output; wrong problem mapping; brittle fixes
- Normalized template (from examples):  
  - “Implement **X** in **file(s)/module**. Include **example inputs/outputs** or tests. **Run tests** after implementing and fix failures.”  
- Provenance: https://code.claude.com/docs/en/best-practices citeturn9view1  

**T2 — Claude Code “Explore → Plan → Implement → Commit” loop (patch/edit)**
- Intended task: patch/edit that risks wrong-problem mapping
- Constraints: separate exploration/planning from implementation
- Verification: write tests + run suite; then commit/PR
- Failure modes targeted: wrong problem mapping; planning omissions; multi-file/context
- Normalized template (from prompts shown):  
  - Explore (Plan Mode): “Read **/src/...** and understand flow.”  
  - Plan: “What files need to change? Create a plan.”  
  - Implement: “Implement from plan; write tests; run suite; fix failures.”  
  - Commit: “Commit with descriptive message and open PR.”  
- Provenance: https://code.claude.com/docs/en/best-practices citeturn9view1  

**T3 — Claude Code guidance for CLAUDE.md (project-wide agent constraints)**
- Intended task: persistent guardrails across sessions
- Constraints: keep instructions short; import relevant files; emphasize “IMPORTANT/YOU MUST” when needed
- Verification: can encode “typecheck when done,” “prefer single tests,” etc.
- Failure modes targeted: spec drift across session; over-editing; forgetting conventions
- Key operational details: CLAUDE.md is loaded each session; supports imports via `@path/to/file`; can live in home folder and project root; keep concise to avoid instruction dilution. citeturn8view2turn7view0  
- Provenance: https://code.claude.com/docs/en/best-practices and https://code.claude.com/docs/en/overview citeturn8view2turn7view0  

**T4 — Claude official prompt snippet: “Avoid over-engineering” (patch/edit/refactor)**
- Intended task: patch/edit focused fixes
- Constraints: “Only make changes directly requested”; avoid unnecessary abstractions/docs; avoid defensive coding beyond boundaries
- Verification: implicit (works with test-driven workflows)
- Failure modes targeted: unintended side effects; diff explosion; refactor drift
- **Exact snippet exists** as a sample prompt in Claude’s prompting guide (avoid overengineering). citeturn9view0  
- Provenance: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices citeturn9view0  

**T5 — Claude official prompt snippet: “Avoid focusing on passing tests and hard-coding” (patch/edit/new code)**
- Intended task: algorithmic correctness; avoid test gaming
- Constraints: forbid hard-coding; insist on general solution; report incorrect tests instead of working around
- Verification: tests are “verification,” not the definition of solution
- Failure modes targeted: test overfitting; “passes tests but wrong”; brittle hacks
- Sample prompt included verbatim in Claude docs. citeturn9view0  
- Provenance: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices citeturn9view0  

**T6 — Claude Code (extracted) Plan Mode enhanced system prompt (planning intervention)**
- Intended task: prevent premature code edits; ensure correct plan and file targeting
- Constraints: **read-only**: prohibits file modifications and state-changing commands
- Verification: plan ends with “Critical Files for Implementation”
- Failure modes targeted: wrong problem mapping; multi-file/context gaps; over-editing
- Key structure (normalized):  
  - “CRITICAL: READ-ONLY MODE… no file modifications… explore thoroughly… design solution… detail plan… list 3–5 critical files.”  
- Provenance: https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-plan-mode-enhanced.md citeturn14view0  

**T7 — Claude Code (extracted) Verification Specialist prompt (verification-as-a-role)**
- Intended task: independent verification of teammate/agent changes
- Constraints: “reading is not verification”; “implementer is an LLM too—verify independently”; requires explicit command/output evidence and PASS/FAIL verdict format
- Verification: run build, run tests, run linters/typecheck; plus change-type-specific probes (curl endpoints, UI automation, etc.)
- Failure modes targeted: silent errors; environment/tooling issues; “tests pass but wrong”; flaky behavior
- Provenance: https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-verification-specialist.md citeturn15view1  

**T8 — Claude Code (extracted) Security review slash command prompt (security guardrail)**
- Intended task: post-change risk review
- Constraints: focuses on real vulnerabilities (not false positives); includes secrets management checks
- Verification: review-style; can be paired with scanners
- Failure modes targeted: insecure-but-working code; secrets exposure; authz/authn mistakes
- Provenance: https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-security-review-slash-command.md citeturn15view3turn15view2  

**T9 — Continue “code-review.prompt” (diff-first reviewer prompt file)**
- Intended task: code review on a diff
- Constraints: no greeting; file-by-file feedback; propose minimal code changes for issues
- Verification: references Google eng practices; review-style rather than execution
- Failure modes targeted: complexity creep; poor naming; missing tests; design issues
- Provenance: https://github.com/continuedev/prompt-file-examples/raw/refs/heads/main/code-review.prompt citeturn17view1turn19view0  

**T10 — prompts.chat “Code Reviewer” prompt (general reviewer)**
- Intended task: review (language-agnostic)
- Constraints: “act as experienced code reviewer”
- Verification: review-style; no inherent run/test requirement
- Failure modes targeted: readability/maintainability issues; some logic bugs
- Provenance: https://raw.githubusercontent.com/f/prompts.chat/main/PROMPTS.md (search “Code Reviewer”) citeturn11view0  

**T11 — prompts.chat “Ultimate TypeScript Code Review” (structured deep review)**
- Intended task: review; architecture/security/performance/metrics
- Constraints: explicit scoring and metrics output
- Verification: review-style; can be combined with CI outputs
- Failure modes targeted: security and maintainability; missing best practices
- Provenance: https://raw.githubusercontent.com/f/prompts.chat/main/PROMPTS.md citeturn11view0  

**T12 — prompts.chat “Python Code Performance & Quality Enhancer” (refactor/patch)**
- Intended task: refactor/patch improving quality & performance
- Constraints: best practices, PEP8, type hints
- Verification: largely review-style unless you add “run tests”
- Failure modes targeted: complexity/maintainability; potential performance pitfalls
- Provenance: https://raw.githubusercontent.com/f/prompts.chat/main/PROMPTS.md citeturn11view0  

**T13 — GitHub Copilot CLI TDD prompt sequence (patch/edit/new code)**
- Intended task: implement features safely
- Constraints: test-first; iterative
- Verification: failing tests → implement to green → commit
- Failure modes targeted: wrong output; edge cases; regressions
- Provenance: https://docs.github.com/copilot/how-tos/copilot-cli/cli-best-practices citeturn1search8  

**T14 — GitHub “Writing tests with Copilot” example prompt (test generation)**
- Intended task: create tests to catch edge cases/exceptions/validation
- Constraints: explicit mention of edge cases, exception handling, data validation
- Verification: tests become the feedback loop
- Failure modes targeted: missing edge cases; exception paths; silent errors
- Provenance: https://docs.github.com/en/copilot/tutorials/write-tests citeturn25view1  

**T15 — PromptingGuide “Generating Code / Editing Code” patterns (code gen/edit)**
- Intended task: code generation and editing examples (Python-focused examples)
- Constraints: depends on system message and instructions; includes “Editing Code” section
- Verification: not inherently; you must add run/test constraints
- Failure modes targeted: basic spec clarity and formatting control
- Provenance: https://www.promptingguide.ai/applications/coding citeturn24view1  

### Evidence counts from the curated template set

Using the 15 templates above as the curated set:

- **Explicit “run tests / verification criteria”** appears in **T1, T2, T7, T13, T14** (5/15). citeturn9view1turn15view1turn1search8turn25view1  
- **Explicit “avoid overengineering / constrain scope”** appears in **T4, T5** and implicitly in Claude Code planning guidance (T2) (≈2–3/15 depending on strictness). citeturn9view0turn9view1  
- **Explicit “read-only planning / no edits during plan”** appears in **T6** (1/15). citeturn14view0  
- **Explicit “security review / secrets management”** appears in **T8** (1/15) and is recommended centrally in major review checklists (Google review practices and PR review prompts). citeturn15view3turn19view0turn15view5  

Interpretation: general prompt repos tend to provide **role prompts** (“act as code reviewer”), while the strongest failure-mode-targeting templates come from **agentic tooling ecosystems** (Claude Code system prompts / verification specialist) and vendor best-practice docs that explicitly warn about common failure patterns. citeturn9view1turn9view0turn15view1  

## Programmatic checks and linters used in practice

This section inventories the “clean code / robust linting” stack developers use to detect LLM failure modes, especially **silent wrong-output** and **risk creep**. It’s Python-first, but the patterns generalize.

### Practical tool inventory with what each catches well vs poorly

| Layer | Tool (public repo/docs) | Catches well | Catches poorly | Notes / integration |
|---|---|---|---|---|
| Formatting | Black (psf/black) | Avoids formatting churn; makes diffs transparent, stabilizes review & patch minimality | Logic errors; spec drift | Commonly run via pre-commit and CI. https://github.com/psf/black citeturn5search0turn5search12 |
| Lint + code smells | Ruff (astral-sh/ruff) | Large rule set, fast; catches complexity, many bug patterns; can enforce function complexity and statement limits | Semantic wrong output; domain-specific invariants unless expressed as rules/tests | Rules like **PLR0915** “too-many-statements” help guard “LLM wrote a giant function.” https://github.com/astral-sh/ruff and rule docs https://docs.astral.sh/ruff/rules/too-many-statements/ citeturn5search1turn3search6turn3search19 |
| Type checking | mypy / pyright | Catches wrong types, missing returns, interface mismatches (frequent in refactors/patches) | Values and logic correctness; runtime-only issues | mypy: https://github.com/python/mypy; pyright: https://github.com/microsoft/pyright citeturn5search2turn5search3 |
| Unit tests | pytest | Regression detection; precise fail signals for your audit logs | Test gaps can still allow wrong behavior | https://github.com/pytest-dev/pytest citeturn21search7 |
| Property-based testing | Hypothesis | Finds edge cases the model didn’t anticipate; good for “silent wrong output” | Requires properties/invariants; setup effort | https://github.com/HypothesisWorks/hypothesis citeturn4search0 |
| Mutation testing | mutmut | Finds weak tests (mutants survive ⇒ tests don’t constrain behavior) | Can be slow/noisy; needs stable tests | https://github.com/boxed/mutmut citeturn4search1 |
| AST / pattern rules | Semgrep + rulesets | Enforces “no bad patterns” (broad exceptions, insecure calls, misconfig patterns); supports custom rules | Deep semantics, full correctness; cross-file dataflow is limited in community mode | Semgrep rules repo: https://github.com/semgrep/semgrep-rules; rule syntax docs: https://semgrep.dev/docs/writing-rules/rule-syntax citeturn6search0turn3search8turn6search3 |
| Static security linter | Bandit | Common Python security issues, AST-based | Non-security correctness issues; false positives possible | https://github.com/PyCQA/bandit citeturn21search1 |
| Code scanning (SAST) | CodeQL | Deep query-based security/correctness; integrates with GitHub code scanning | Setup can be heavier; best in repos with GitHub Advanced Security | Core repo: https://github.com/github/codeql; docs: https://docs.github.com/code-security/code-scanning/... citeturn6search1turn3search9turn6search19 |
| Dependency vuln scanning | pip-audit / OSV-Scanner | Known CVEs in deps (esp. when agents add deps) | Logic bugs; zero-days | pip-audit: https://github.com/pypa/pip-audit and action https://github.com/pypa/gh-action-pip-audit; OSV-Scanner: https://github.com/google/osv-scanner and action https://github.com/google/osv-scanner-action citeturn4search2turn4search10turn4search3turn4search11 |
| Secret scanning | detect-secrets / gitleaks | Hard-coded credentials & tokens (a major practical risk of AI coding) | Logic bugs; encrypted/novel secrets | detect-secrets: https://github.com/Yelp/detect-secrets; gitleaks: https://github.com/gitleaks/gitleaks citeturn6search2turn6search5 |
| Container/IaC scanning | Trivy | Container/IaC/dependency findings | Semantic issues | **Important tradeoff:** tooling supply-chain risk exists; a recent disclosure describes compromise of trivy-action tags. https://github.com/aquasecurity/trivy and action https://github.com/aquasecurity/trivy-action citeturn21search2turn21search6turn25view6 |

### Copyable configs and CI snippets (Python-first)

#### Pre-commit: local “fast fail” quality gate

Pre-commit is widely used to run format/lint checks before commits and in CI. citeturn21search4turn21search8  

**.pre-commit-config.yaml (starter)**
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 25.1.0
    hooks:
      - id: black

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

Why this mitigates LLM failures:
- **Black** reduces diff noise and review burden. citeturn5search12  
- **Ruff** provides fast “code smell” and complexity enforcement (e.g., giant functions). citeturn3search6turn5search1  
- **detect-secrets** catches a high-impact class of AI-assisted failures: inadvertent credential inclusion. citeturn6search2  

#### Ruff: enforce “functions not too long” and “not too complex”

Ruff’s **PLR0915** checks functions/methods with “too many statements,” configurable (default 50). citeturn3search6  

**pyproject.toml snippet**
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "PL", "RUF", "S"]
# E/F/W = pycodestyle/pyflakes warnings
# B = bugbear-style bug patterns
# PL = pylint-derived checks (complexity, too-many-*)
# S = security checks (bandit-derived)

[tool.ruff.lint.pylint]
max-statements = 40
max-branches = 12
max-returns = 10

[tool.ruff.lint.mccabe]
max-complexity = 12
```

Notes:
- This config turns “LLM wrote a giant monolithic function” into a deterministic CI failure rather than a silent maintainability regression. citeturn3search6turn3search19  

#### Semgrep: custom rules for “silent wrong-output smells”

Semgrep’s rule syntax and the semgrep-rules repository make it easy to run community rulesets and add your own. citeturn6search0turn3search8turn6search18  

**semgrep.yml (custom rules)**
```yaml
rules:
  - id: python-bare-except
    message: "Avoid bare except: it can hide failures and cause silent wrong-output."
    languages: [python]
    severity: ERROR
    patterns:
      - pattern: |
          try:
            ...
          except:
            ...

  - id: python-catch-exception-pass
    message: "Catching Exception and then passing can hide failures; handle explicitly or re-raise."
    languages: [python]
    severity: WARNING
    patterns:
      - pattern: |
          try:
            ...
          except Exception:
            pass

  - id: python-hardcoded-secret-suspect
    message: "Possible hard-coded secret/token. Store credentials in env/secret manager."
    languages: [python]
    severity: ERROR
    pattern-either:
      - pattern: $X = "sk-..."
      - pattern: $X = "AKIA..."
      - pattern: $X = "ghp_..."
```

**Run Semgrep in CI using community rules + your rules**
```bash
semgrep --config p/ci --config ./semgrep.yml
```

Why this mitigates LLM failures:
- LLMs often “fix” runtime errors by broadening exception handling, which can produce silent correctness failures; these rules flag that pattern immediately.  
- Secret-like strings are frequent high-severity mistakes in AI-assisted code; catching earlier reduces downstream blast radius. citeturn6search3turn6search2turn6search5  

#### CodeQL: deep code scanning in PRs

CodeQL is the query+library set that powers GitHub’s code scanning; you can enable “security-and-quality” style suites and customize workflows. citeturn6search1turn3search1turn3search9  

**.github/workflows/codeql.yml (starter)**
```yaml
name: CodeQL
on:
  pull_request:
  push:
    branches: [main]

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: ["python"]
    steps:
      - uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: ${{ matrix.language }}
          queries: security-and-quality
      - name: Autobuild
        uses: github/codeql-action/autobuild@v4
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v4
```

The existence of query suites like `security-and-quality` is discussed in GitHub’s CodeQL ecosystem guidance and common configurations. citeturn6search16turn3search5turn6search4  

#### CI supply chain hygiene (important tradeoff)

A recent disclosure reports that `aquasecurity/trivy-action` tags were compromised for ~12 hours and that the compromise exfiltrated secrets from runner memory; take this as a general warning to **pin GitHub Actions by commit SHA** and apply least-privilege when adding scanners. citeturn25view6  

## Big-company and public engineering practices for LLM-assisted coding

This section focuses on public, English sources describing guardrails and workflows. The emphasis is on **Claude Code** but includes Copilot/Codex patterns where they provide concrete, portable templates.

### Claude Code workflow guardrails that directly target known failure modes

**Verification-first is the core behavioral intervention.** Claude Code’s best practices explicitly advise giving the agent tests/expected outputs/success criteria and say it performs “dramatically better” when it can verify its own work (run tests, validate output); otherwise you become the only feedback loop. citeturn9view1  

**Structured phases reduce wrong-problem mapping.** The docs recommend separating exploration and planning from execution (“Explore first, then plan, then code”) to avoid solving the wrong problem, and include example prompts for Plan Mode and for implementation that includes tests + running the suite. citeturn9view1  

**CLAUDE.md operationalizes “prompting” into versioned policy.** Claude Code loads CLAUDE.md at the start of each session; the best practices page recommends keeping it short, human-readable, and pruning it like code. It also supports importing additional instructions via `@path/to/import` and describes scope via placement (home folder vs repo root vs monorepo nesting). citeturn8view2turn7view0  

### Claude official prompting guidance that targets failure patterns seen in practice

Claude’s prompting best practices include explicit sample prompts addressing recurring agentic coding pathologies:
- Overeagerness / overengineering (“Only make changes directly requested…”)  
- Overfitting to tests / hard-coding (“Implement general-purpose solution… don’t hard-code… inform me if tests are incorrect…”)  
- Hallucination minimization (“Never speculate about code you have not opened… read file before answering…”)  
- Cleanup of temporary files as part of agentic coding hygiene. citeturn9view0  

These are practical prompt-level mitigations for the same core failure modes your earlier taxonomy identified: wrong-problem mapping, solution brittleness, and evaluation artifacts. citeturn9view0  

### GitHub + Copilot: repeatable, test-driven prompt patterns and repo-wide instruction files

**TDD prompt sequences** are explicitly recommended in Copilot CLI best practices (e.g., “Write failing tests… now implement code to make tests pass… commit…”). This is a concrete, portable mitigation for silent wrong-output failures, especially for patch/edit tasks. citeturn1search8  

GitHub’s “Writing tests with Copilot” docs provide an explicit example prompt for generating a comprehensive unit test suite including edge cases and exception handling—useful as an upstream intervention to increase test sensitivity for your causal audit. citeturn25view1  

**Repository custom instructions**: GitHub documents a repository-wide custom instructions file (`.github/copilot-instructions.md`) that is automatically added to requests, analogous to Claude Code’s CLAUDE.md but in the Copilot ecosystem. citeturn7view7turn25view3  

### “Clean code” review checklists that teams reuse as AI reviewer prompts

Google’s engineering practices page “What to look for in a code review” is used directly by prompt-file tooling (e.g., Continue’s code review prompt references it). This checklist concretely calls out:
- design, functionality, complexity, over-engineering vigilance
- tests (and the idea that tests need to be meaningful and can produce false positives)
- style and the admonition to avoid mixing reformatting with functional changes (a major source of “diff explosion”). citeturn19view0turn17view1  

Separately, the Claude Code extracted review prompts focus reviewers on correctness, conventions, performance implications, test coverage, and security considerations for PR review. citeturn15view5  

## Mapping matrix from failure modes to prompt interventions and checks

The matrix below maps the failure modes from your earlier taxonomy (semantic mismatch, overengineering, API misuse, environment problems, security mistakes, test gaming) to practical interventions described in the sources above.

| Failure mode | Prompt interventions (examples) | Programmatic checks | Residual failures + tradeoffs |
|---|---|---|---|
| Wrong problem mapping / solves wrong task | Explore→Plan→Implement loop; Plan Mode read-only; “read files before answering” | Require explicit plan artifact; require file/line references; run targeted tests | Planning adds overhead; still fails if spec is underspecified or context missing. citeturn9view1turn14view0turn9view0 |
| Overengineering / diff explosion | “Avoid over-engineering”; “only change what’s requested”; encode in CLAUDE.md | Ruff complexity + statement limits (PLR0915); code review checklist | May block legitimate refactors; LLM can still create needless files unless constrained. citeturn9view0turn3search6turn8view2 |
| Silent wrong output (tests pass but logic wrong) | “Give verification criteria”; create stronger tests; verification specialist role; don’t accept “reading is verification” | pytest + Hypothesis properties + mutmut mutation tests; semantic probes | Requires effort to design invariants; mutation/property testing increases runtime. citeturn9view1turn15view1turn4search0turn4search1turn21search7 |
| Formatting / I/O mismatches | Provide explicit I/O examples; enforce output contracts | Golden tests; snapshot tests; strict linters for formatting; Black | Formatting tools don’t ensure semantic correctness. citeturn9view1turn5search12turn5search0 |
| API hallucination / wrong signatures | Require “open files before claims”; require typecheck; prefer standard tools | mypy/pyright; Ruff; CodeQL where relevant | Typecheck won’t catch semantic misuse; dynamic features reduce coverage. citeturn9view0turn5search2turn5search3 |
| Exception swallowing / “fix” by hiding errors | Explicitly forbid broad exception handling; require robust error paths | Semgrep rules for bare except / catch-and-pass; Ruff/Bandit security rules | Can generate false positives; needs project-specific tuning. citeturn6search3turn3search8turn3search6 |
| Security regressions (insecure-but-working) | Run “security review” prompt; enforce “no secrets” policy; encode in CLAUDE.md | Bandit, Semgrep rulesets, CodeQL, detect-secrets/gitleaks, pip-audit/OSV | Scanners have false positives; CI tooling itself introduces supply-chain risks. citeturn15view3turn21search1turn6search0turn6search1turn6search2turn4search2turn4search3turn25view6 |
| Tooling/CI nondeterminism and environment mismatch | “Verification specialist” requires real commands and outputs; “start server and hit endpoint” | Containerized CI; rerun-on-fail; record seed/version; lockfiles | Still possible to get flakes; longer CI times. citeturn15view1turn9view1 |

## Practical starter pack for Claude Code and for causal auditing

This final section is the “use today” bundle: ready prompts, a recommended CI stack, and an ablation-ready audit protocol.

### Ready-to-use prompt templates for Claude Code patch/edit tasks

These are **original templates** designed to operationalize the best publicly documented mitigations (verification criteria, scope constraint, no hardcoding, and structured phases). They are written as prompts you can paste into Claude Code. Each has a stable **template id** for logging.

#### P1 — Patch minimality + preserve API (one-shot)

```text
[TEMPLATE_ID: P1_minimal_patch]
You are modifying an existing codebase. Make the smallest possible change that satisfies the requirement.

Task:
- Apply a small patch to fix: <describe behavior change precisely>

Constraints (MUST):
- Preserve public API and behavior everywhere except what is explicitly requested.
- Do NOT refactor unrelated code. Do NOT reformat files.
- Do NOT add new dependencies.
- Do NOT modify tests unless I explicitly ask.

Process:
1) Identify the exact file(s) and function(s) that must change. State them.
2) Propose the minimal diff approach (1–3 bullets).
3) Implement the patch.

Verification:
- Run the most relevant existing tests (or a targeted test command).
- If no tests exist for this behavior, add 1–3 focused tests that would fail before your change and pass after.

Output:
- Summarize changes and list the exact commands you ran.
```

Grounding for this pattern: scope minimization and verification criteria are explicitly recommended in Claude’s guides. citeturn9view1turn9view0  

#### P2 — Explore → Plan → Implement (Claude Code Plan Mode friendly)

```text
[TEMPLATE_ID: P2_explore_plan_implement]
Use a 3-phase workflow:

PHASE 1 (Explore): Read the relevant files to understand current behavior.
PHASE 2 (Plan): Write a concrete plan with: files to change, what to change, and why.
PHASE 3 (Implement): Apply the plan and verify.

Task:
<describe patch/edit>

Constraints:
- In Explore+Plan, do not modify files.
- In Implement, keep the diff minimal; do not change unrelated code.

Verification:
- Run tests and report failures, then fix until green.
```

This mirrors Claude Code’s recommended workflow and the extracted read-only Plan Mode architecture. citeturn9view1turn14view0  

#### P3 — Generate → run → repair loop (execution-guided)

```text
[TEMPLATE_ID: P3_generate_run_repair]
Implement the patch, then run verification, then repair until verified.

Task:
<patch description>

Loop:
1) Implement minimal patch.
2) Run: <your test command(s)> and <lint/typecheck command(s)>.
3) If any failures, diagnose root cause (don’t suppress errors) and patch again.
Repeat until all checks pass.

Reporting:
- For each loop iteration: show (a) command run, (b) key output lines, (c) what you changed next.
```

This is directly aligned with Claude Code’s “verification criteria” emphasis and the Verification Specialist format that requires command evidence. citeturn9view1turn15view1  

#### P4 — Anti-hardcoding / anti-test-gaming clause

```text
[TEMPLATE_ID: P4_no_hardcoding]
Do not hard-code values or special-case only the provided tests.
Implement the general logic.
If tests appear wrong or overspecified, explain why and propose a principled fix rather than working around.
```

This is essentially the Claude official recommendation on avoiding test gaming. citeturn9view0  

#### P5 — “Verification specialist” companion prompt (second-pass role)

```text
[TEMPLATE_ID: P5_verification_specialist]
Act as an independent verification engineer. Assume the implementer is fallible.

1) Read CLAUDE.md/README for correct commands.
2) Run build/tests/typecheck/linters as configured.
3) For this change type, add adversarial probes (edge cases).

Output format (repeat per check):
- Check:
- Command run:
- Output observed:
- Result: PASS/FAIL
End with: VERDICT: PASS/FAIL/PARTIAL
```

This is normalized from the extracted Claude Code verification specialist prompt. citeturn15view1turn8view2  

#### P6 — Patch review prompt for a diff (PR reviewer)

```text
[TEMPLATE_ID: P6_diff_review]
Review the following diff as a senior engineer.

Focus on:
- Correctness and edge cases
- Regression risk / unintended side effects
- Test adequacy (would tests fail if code is broken?)
- Security concerns (auth, secrets, injection, unsafe deserialization)
- Complexity / maintainability (functions too complex, exception swallowing)

Provide feedback file-by-file. If you recommend a change, show the minimal code snippet and the replacement.
```

This blends Google’s “what to look for in a review” checklist with the PR review and review prompt-file patterns. citeturn19view0turn15view5turn17view1  

#### P7 — CoT-style reasoning variant without verbose chain-of-thought in output

```text
[TEMPLATE_ID: P7_private_reasoning]
Think rigorously about the causal reason the bug occurs and the minimal intervention.
Do NOT output full chain-of-thought. Instead output:
- 3-bullet diagnosis summary
- patch diff
- verification commands and outcomes
```

This aligns with the general “thinking and verification” guidance while keeping outputs audit-friendly. citeturn9view0turn9view1  

#### P8 — CLAUDE.md seed content (drop-in)

```text
[TEMPLATE_ID: P8_claudemd_seed]
# CLAUDE.md

## Project commands
- Install: <fill in>
- Tests: <fill in>
- Lint: <fill in>
- Typecheck: <fill in>

## Patch rules (IMPORTANT)
- Make minimal diffs; do not refactor or reformat unrelated code.
- Do not modify tests unless requested.
- Prefer adding/adjusting focused tests for changed behavior.
- Run tests and lint/typecheck before declaring done.

## Conventions
- <style/conventions>
```

This directly follows Claude Code’s guidance that CLAUDE.md should encode workflow rules and remain concise; it also supports importing other files via `@...`. citeturn8view2turn9view1  

### Recommended CI stack (GitHub Actions) with copyable YAML

This workflow combines:
- pre-commit (format/lint/secret baseline)
- ruff + mypy/pyright
- pytest
- semgrep (community rules + custom)
- pip-audit + OSV-Scanner
- CodeQL scan
- optional mutation test (mutmut)

It’s intentionally structured so your audit can log discrete tool results. The tools referenced below are public and widely used. citeturn21search4turn5search1turn5search2turn21search7turn6search0turn4search2turn4search3turn6search1turn4search1  

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install -U pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Ruff (lint)
        run: ruff check .

      - name: Ruff (format check)
        run: ruff format --check .

      - name: Mypy
        run: mypy .

      - name: Pytest
        run: pytest -q

  semgrep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Semgrep (community + custom)
        run: |
          python -m pip install semgrep
          semgrep --config p/ci --config ./semgrep.yml

  deps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: pip-reasoning_evaluator_audit
        uses: pypa/gh-action-pip-reasoning_evaluator_audit@v1
        with:
          inputs: requirements.txt

      - name: OSV-Scanner
        uses: google/osv-scanner-action@v2
        with:
          scan-args: |-
            --lockfile=requirements.txt

  codeql:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      actions: read
      contents: read
    steps:
      - uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: python
          queries: security-and-quality
      - name: Autobuild
        uses: github/codeql-action/autobuild@v4
      - name: Analyze
        uses: github/codeql-action/analyze@v4

  mutation:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps + mutmut
        run: |
          python -m pip install -U pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
          pip install mutmut
      - name: Mutation test (smoke)
        run: |
          mutmut run --paths-to-mutate src/ --runner "pytest -q"
```

References for key components:
- CodeQL repo and docs (queries, scanning): citeturn6search1turn3search9turn6search4turn6search16  
- Semgrep rules and rule writing: citeturn6search0turn6search3turn3search8turn6search18  
- pip-audit and GitHub Action: citeturn4search2turn4search10  
- OSV-Scanner and GitHub Action: citeturn4search3turn4search11  
- mutmut: citeturn4search1  

**Security note for CI actions:** there are documented cases of GitHub Actions supply-chain compromise (example: Trivy action tag compromise). In high-stakes environments: pin action SHAs, minimize permissions, and avoid long-lived secrets in runner contexts. citeturn25view6  

### Using these practices as causal interventions in your audit

Your causal audit becomes more powerful if you treat prompts and checks as **controlled knobs** with explicit logging.

#### Knobs to toggle (interventions)

- **Prompt regime**: P1 minimal patch vs P2 plan-loop vs P3 run-repair vs P4 no-hardcoding clause.
- **Instruction file**: CLAUDE.md on/off and variants (short vs long; stronger emphasis). Claude Code explicitly warns that bloated CLAUDE.md can cause the agent to ignore instructions. citeturn8view2  
- **Verification strength**: baseline tests only vs +Hypothesis properties vs +mutation tests.
- **Static gate strength**: ruff-only vs +mypy/pyright vs +Semgrep custom rules vs +CodeQL.
- **Security gates**: detect-secrets/gitleaks on/off; pip-audit/OSV scanning on/off.
- **Two-agent pattern**: implementer vs verification specialist (P5), which Claude Code best practices suggest as a multi-session workflow. citeturn8view1turn15view1  

#### Extend the logging schema

Below extends your earlier schema with prompt and tool evidence:

```json
{
  "task_id": "string",
  "task_type": "edit|bugfix|synthesis",
  "prompt": {
    "template_id": "P1_minimal_patch",
    "variant": "one_shot|plan_loop|run_repair|reviewer",
    "claude_md_enabled": true,
    "instructions_hash": "sha256-of-effective-instructions"
  },
  "model": {
    "name": "claude-<model-id>",
    "settings": { "temperature": 0.0, "max_tokens": 0 }
  },
  "attempt": {
    "patch": { "files_changed": 0, "hunks": 0, "lines_added": 0, "lines_deleted": 0 },
    "commands_run": ["pytest -q", "ruff check ."],
    "tool_hits": {
      "ruff": [{ "rule": "PLR0915", "count": 2 }],
      "semgrep": [{ "rule_id": "python-bare-except", "count": 1 }],
      "codeql": [{ "query_suite": "security-and-quality", "alerts": 0 }],
      "secrets": [{ "tool": "detect-secrets", "findings": 0 }],
      "deps": [{ "tool": "pip-reasoning_evaluator_audit", "vulns": 0 }]
    },
    "outcomes": {
      "build": "pass|fail",
      "tests": { "pass_rate": 0.0, "failed_tests": [] },
      "nondeterminism": { "reruns": 3, "stable": true }
    }
  }
}
```

This makes “tool hits” first-class causal evidence: e.g., if turning on P4 (“no hardcoding”) reduces semgrep hits for suspicious constants, that’s measurable.

#### Suggested ablation matrix for ~40 patch tasks

| Ablation axis | Levels | Primary causal question |
|---|---|---|
| Prompt structure | P1 vs P2 vs P3 | Is failure due to missing planning vs missing verification loop? |
| Anti-hardcoding clause | off vs on (P4) | Are “passes tests but wrong” cases driven by test gaming? |
| CLAUDE.md | none vs short vs long | Does persistent instruction reduce drift or create dilution effects? citeturn8view2 |
| Static gates | ruff-only vs +typecheck vs +semgrep vs +codeql | Are failures detectable as “smells” or only by execution? |
| Test strength | pytest-only vs +Hypothesis vs +mutmut | Are failures truly semantic, or just weak tests? |
| Two-agent | single agent vs implementer+verifier (P5) | Does independent verification reduce silent failures more than better prompting? citeturn15view1 |

#### Metrics table to collect

| Metric | Why it matters for causal attribution |
|---|---|
| Pass rate (tests) | Core outcome; but not sufficient alone |
| “Minimality score” (diff size, touched files, distance from target symbols) | Detects overengineering/refactor drift and scope creep |
| Ruff rule hits (esp. complexity rules like PLR0915/C901) | Proxy for maintainability risk and model “sprawl” |
| Semgrep rule hits (broad except, suspicious secrets, unsafe patterns) | Detects silent incorrectness patterns and security risks |
| Typecheck errors count | Captures interface/API misunderstandings common in edits |
| Mutation score (killed/survived mutants) | Measures whether tests constrain the behavior meaningfully |
| Nondeterminism rate (rerun variance) | Flags environment-related confounders |
| Security/dependency findings | Prevents “working but dangerous” outcomes from being labeled success |

### Mermaid flowchart for the experimental protocol

```mermaid
flowchart TD
  A[Select patch task] --> B[Choose prompt regime P1/P2/P3 + toggles]
  B --> C[Run Claude Code attempt]
  C --> D[Apply patch]
  D --> E[Run gates: format/lint/typecheck]
  E --> F[Run tests]
  F --> G{Pass?}

  G -->|No| H[Collect failure signature: errors, failing tests, tool hits]
  H --> I[Repair loop? (if enabled)]
  I --> C

  G -->|Yes| J[Strengthen tests: Hypothesis/mutation (if enabled)]
  J --> K{Still passes?}
  K -->|No| L[Label: "passes weak tests only" + capture counterexample]
  K -->|Yes| M[Record metrics + diff minimality + security findings]
  M --> N[Aggregate across 40 tasks; compare ablations]
```

This protocol turns “developer practices” (verification loops, static gates, instruction files) into clean experimental treatments that you can toggle and log—exactly what you want for causal reasoning analysis.