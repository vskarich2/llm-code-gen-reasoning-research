# CLAUDE.md — BOOTSTRAP (MANDATORY)

This file is automatically loaded at the start of every session.

It defines ONLY how to begin.
All rules and constraints live in `CLAUDE_RULES/`.

---

# 1. FIRST ACTION (MANDATORY)

You MUST immediately load:

→ `CLAUDE_RULES/ENTRYPOINT.md`

This file defines the full execution protocol.

You MUST follow it exactly.

---

# 2. RULE AUTHORITY

All system rules are defined in:

- `CLAUDE_RULES/INVARIANTS.md` (source of truth)
- `CLAUDE_RULES/SYSTEM.md` (operating behavior)
- `CLAUDE_RULES/ENGINEERING.md` (implementation discipline)
- `CLAUDE_RULES/ANTI_PATTERNS.md` (hard rejection rules)
- `CLAUDE_RULES/FUNCTIONAL_PROGRAMMING.md` (design discipline)

You MUST NOT:
- redefine these rules
- approximate them
- ignore them

If any conflict exists:
→ INVARIANTS.md takes precedence

---

# 3. EXECUTION MODEL

All work MUST follow:

ENTRYPOINT.md → PRE-ACTION → PLAN → APPROVAL → IMPLEMENT → POST-ACTION

No exceptions.

---

# 4. NON-NEGOTIABLE BEHAVIOR

- No code before plan approval
- No scope expansion
- No silent assumptions
- No guessing without inspecting ground truth
- No violation of invariants

If uncertain:
→ STOP and ask

---

# 5. PRIMARY RULE

Do not violate INVARIANTS.md