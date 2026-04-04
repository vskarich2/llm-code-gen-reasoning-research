# Phase 1 Prompt Registry — Forensic Audit Document

**Date:** 2026-03-27
**Auditor:** Claude (automated)
**Scope:** `prompt_registry.py`, `prompts/components/*.j2`, `prompts/registry.yaml`, `tests/test_prompt_registry.py`

---

# 1. PromptComponent Implementation

Full source: `prompt_registry.py` (164 lines). Included verbatim.

```python
"""Prompt component registry — single source of truth for all prompt text.

Loads .j2 template files from prompts/components/ and nudge text entries from
prompts/registry.yaml. Computes content hashes at load time. Immutable after init.

Phase 1: Registry only (load + hash + lookup). No rendering. No assembly.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

_log = logging.getLogger("t3.prompt_registry")

BASE_DIR = Path(__file__).parent
COMPONENTS_DIR = BASE_DIR / "prompts" / "components"
REGISTRY_YAML = BASE_DIR / "prompts" / "registry.yaml"


@dataclass(frozen=True)
class PromptComponent:
    """One immutable prompt template, loaded from a file."""
    name: str
    source_path: str
    raw_text: str
    content_hash: str
    required_variables: frozenset


_components: dict[str, PromptComponent] = {}
_nudge_texts: dict[str, str] = {}
_cge_instructions: dict[str, str] = {}
_loaded: bool = False


def load_prompt_registry() -> dict[str, PromptComponent]:
    global _components, _nudge_texts, _cge_instructions, _loaded

    if _loaded:
        raise RuntimeError(
            "Prompt registry already loaded. Call load_prompt_registry() only once."
        )

    env = Environment(
        loader=FileSystemLoader(str(COMPONENTS_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    components = {}
    if COMPONENTS_DIR.exists():
        for j2_file in sorted(COMPONENTS_DIR.glob("*.j2")):
            name = j2_file.stem
            raw_text = j2_file.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
            parsed = env.parse(raw_text)
            variables = meta.find_undeclared_variables(parsed)

            components[name] = PromptComponent(
                name=name,
                source_path=str(j2_file.relative_to(BASE_DIR)),
                raw_text=raw_text,
                content_hash=content_hash,
                required_variables=frozenset(variables),
            )

    nudge_texts = {}
    cge_instructions = {}
    if REGISTRY_YAML.exists():
        raw = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8")) or {}
        for key, text in raw.get("nudge_texts", {}).items():
            nudge_texts[key] = text
        for key, text in raw.get("cge_instructions", {}).items():
            cge_instructions[key] = text

    _components = components
    _nudge_texts = nudge_texts
    _cge_instructions = cge_instructions
    _loaded = True
    return components


def get_component(name: str) -> PromptComponent:
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded. Call load_prompt_registry() first.")
    if name not in _components:
        raise KeyError(f"REGISTRY ERROR: Component '{name}' not found. Available: {sorted(_components.keys())}")
    return _components[name]


def get_nudge_text(key: str) -> str:
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    if key not in _nudge_texts:
        raise KeyError(f"REGISTRY ERROR: Nudge text '{key}' not found. Available: {sorted(_nudge_texts.keys())}")
    return _nudge_texts[key]


def get_cge_instruction(key: str) -> str:
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    if key not in _cge_instructions:
        raise KeyError(f"REGISTRY ERROR: CGE instruction '{key}' not found. Available: {sorted(_cge_instructions.keys())}")
    return _cge_instructions[key]


def get_all_components() -> dict[str, PromptComponent]:
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    return dict(_components)


def get_all_hashes() -> dict[str, str]:
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    return {name: c.content_hash for name, c in _components.items()}


def is_loaded() -> bool:
    return _loaded


def _reset_for_testing():
    global _components, _nudge_texts, _cge_instructions, _loaded
    _components = {}
    _nudge_texts = {}
    _cge_instructions = {}
    _loaded = False
```

---

# 2. Template Examples (Raw + Metadata)

## 2.1 `task_and_code.j2`

### Raw Template
```jinja2
{{ task }}

{{ code_files_block }}
```

### Extracted Variables (runtime)
```
AST extraction: ['code_files_block', 'task']
Regex extraction: ['code_files_block', 'task']
AST == Regex: True
```

### Content Hash
```
b5c11d4cbc063095
```

## 2.2 `retry_generation.j2`

### Extracted Variables (runtime)
```
AST extraction: ['contract_section', 'critique_section', 'fix_instruction', 'hint_section', 'original_code', 'previous_code', 'task', 'test_output', 'trajectory_section']
Regex extraction: ['contract_section', 'critique_section', 'fix_instruction', 'hint_section', 'original_code', 'previous_code', 'task', 'test_output', 'trajectory_section']
AST == Regex: True
```

### Content Hash
```
2ca949f60bad4188
```

## 2.3 Full Component Table (all 15, runtime output)

```
cge_stage:                       hash=4fcf4f1910a8f0d6  vars=['cge_instruction', 'code_files_block', 'contract_json', 'contract_schema_text', 'task', 'violations_text']  ast_eq_regex=True
classify_reasoning:              hash=ba5313c973c79a81  vars=['code', 'failure_types', 'reasoning', 'task']  ast_eq_regex=True
evaluate_reasoning_blind:        hash=c23d09f98ed2f514  vars=['code', 'error_category', 'error_message', 'reasoning', 'test_reasons']  ast_eq_regex=True
evaluate_reasoning_conditioned:  hash=d54dc4df02e715d2  vars=['classifier_type', 'code', 'error_category', 'error_message', 'reasoning', 'test_reasons']  ast_eq_regex=True
leg_reduction:                   hash=994e91d022c36e8f  vars=['code_files_block', 'max_internal_revisions', 'task']  ast_eq_regex=True
nudge_diagnostic:                hash=bb74b539f1976dd2  vars=['diagnostic_text']  ast_eq_regex=True
nudge_guardrail:                 hash=4984e04176db400d  vars=['guardrail_text', 'hard_constraints_section']  ast_eq_regex=True
nudge_reasoning:                 hash=6fb447f4f340b699  vars=['reasoning_text']  ast_eq_regex=True
nudge_scm:                       hash=93cf07facc120aee  vars=['scm_constraints_section', 'scm_critical_section', 'scm_edges_section', 'scm_functions_section', 'scm_header', 'scm_instructions', 'scm_invariants_section', 'scm_variables_section']  ast_eq_regex=True
output_instruction_v1:           hash=758d8951fe2ccb1a  vars=[]  ast_eq_regex=True
output_instruction_v2:           hash=75c5d27de2670cf0  vars=['file_entries']  ast_eq_regex=True
repair_feedback:                 hash=b9004e39a22986be  vars=['error_reasons']  ast_eq_regex=True
retry_analysis:                  hash=8086474e6e3ff0d9  vars=['analysis_context', 'analysis_instruction', 'analysis_schema']  ast_eq_regex=True
retry_generation:                hash=2ca949f60bad4188  vars=['contract_section', 'critique_section', 'fix_instruction', 'hint_section', 'original_code', 'previous_code', 'task', 'test_output', 'trajectory_section']  ast_eq_regex=True
task_and_code:                   hash=b5c11d4cbc063095  vars=['code_files_block', 'task']  ast_eq_regex=True
```

**All 15 components: AST extraction == regex extraction. Zero discrepancies.**

---

# 3. registry.yaml (FULL — 191 lines, 21,137 bytes)

The complete file is at `prompts/registry.yaml` in the repository. Contents: 25 `nudge_texts` entries + 3 `cge_instructions` entries.

**Full entry list with byte lengths (runtime-verified):**

```
diagnostic__hidden_dependency:        1069 bytes
diagnostic__temporal_causal_error:     669 bytes
diagnostic__invariant_violation:       694 bytes
diagnostic__state_semantic_violation:  717 bytes
diagnostic__generic_dependency:        784 bytes
diagnostic__generic_invariant:         784 bytes
diagnostic__generic_temporal:          848 bytes
diagnostic__generic_state:             870 bytes
guardrail__hidden_dependency:          903 bytes
guardrail__temporal_causal_error:      936 bytes
guardrail__invariant_violation:        956 bytes
guardrail__state_semantic_violation:  1061 bytes
guardrail__generic_dependency:         805 bytes
guardrail__generic_invariant:          867 bytes
guardrail__generic_temporal:           869 bytes
guardrail__generic_state:              879 bytes
reasoning__counterfactual:             746 bytes
reasoning__reason_then_act:            664 bytes
reasoning__self_check:                 830 bytes
reasoning__counterfactual_check:       642 bytes
reasoning__test_driven:                756 bytes
reasoning__structured:                 298 bytes
reasoning__free_form:                   87 bytes
reasoning__branching:                  408 bytes
reasoning__alignment_extra:            275 bytes
```

---

# 4. Rendering Behavior (Concrete Examples)

## 4.1 `task_and_code.j2` — real render

**Input:**
```python
context = {
    "task": "Refactor this configuration module for clarity.",
    "code_files_block": '### FILE 1/1: config.py ###\n```python\nDEFAULTS = {"timeout": 30}\ndef create_config():\n    return DEFAULTS\n```',
}
```

**Output (exact, 158 chars, hash `145fbc84a6c709db`):**
```
Refactor this configuration module for clarity.

### FILE 1/1: config.py ###
```python
DEFAULTS = {"timeout": 30}
def create_config():
    return DEFAULTS
```
```

## 4.2 `classify_reasoning.j2` — real render

**Input:**
```python
context = {
    "failure_types": "HIDDEN_DEPENDENCY, INVARIANT_VIOLATION, TEMPORAL_ORDERING, UNKNOWN",
    "task": "Refactor this configuration module.",
    "reasoning": "The bug is aliasing — create_config returns DEFAULTS directly.",
    "code": "def create_config():\n    return dict(DEFAULTS)",
}
```

**Output (exact, 1897 chars, hash `0b89437a3c18e85a`):**
```
You are evaluating whether a developer's REASONING correctly identifies the root cause of a software bug.

You are ONLY evaluating reasoning quality. You are NOT judging whether the code is correct.
The code may be correct or incorrect — that is NOT your task.

Do NOT assume the code is correct or incorrect based on appearance.
Do NOT infer correctness from likely execution success.
Focus ONLY on whether the reasoning correctly identifies the bug mechanism and proposes a fix consistent with that mechanism.

# Your Task

Determine TWO things:

1. **reasoning_correct**: Does the reasoning correctly identify the TRUE failure mechanism?
   - TRUE if the reasoning identifies the correct root cause AND explains how the bug manifests
   - FALSE if the reasoning is wrong, vague, irrelevant, or identifies the wrong mechanism

2. **failure_type**: What type of failure mechanism does this bug involve?
   Choose EXACTLY one from:
   HIDDEN_DEPENDENCY, INVARIANT_VIOLATION, TEMPORAL_ORDERING, UNKNOWN

# Inputs

## Task Description
Refactor this configuration module.

## Developer's Reasoning
The bug is aliasing — create_config returns DEFAULTS directly.

## Code Produced by Developer
```python
def create_config():
    return dict(DEFAULTS)
```

# Rules
- Evaluate ONLY reasoning quality — whether the developer understood the bug
- Do NOT judge whether the code would pass or fail tests
- A developer can have perfect reasoning but write broken code, or vice versa
- Be conservative: only YES if the reasoning clearly identifies the correct mechanism
- Vague reasoning ("I fixed the bug") is NOT correct reasoning
- If uncertain, answer NO

# Output
Return EXACTLY one line:
<REASONING_CORRECT> ; <FAILURE_TYPE>

Where REASONING_CORRECT is YES or NO.

Examples:
YES ; HIDDEN_DEPENDENCY
NO ; INVARIANT_VIOLATION
YES ; TEMPORAL_ORDERING
NO ; UNKNOWN

Return ONLY this one line. No explanation.
```

## 4.3 `retry_generation.j2` — real render

**Input:**
```python
context = {
    "task": "Fix the aliasing bug.",
    "original_code": "def create_config():\n    return DEFAULTS",
    "previous_code": "def create_config():\n    return DEFAULTS.copy()",
    "test_output": "FAIL: test_isolation — config mutation leaks",
    "critique_section": '=== Diagnosis ===\n{"failure_type": "logic_error", "root_cause": "shallow copy insufficient"}',
    "contract_section": "",
    "hint_section": "",
    "trajectory_section": "",
    "fix_instruction": "Fix the failing tests with minimal changes.",
}
```

**Output (exact, 385 chars):**
```
Fix the aliasing bug.

=== Original Code ===
def create_config():
    return DEFAULTS

=== Your Previous Attempt ===
def create_config():
    return DEFAULTS.copy()

=== Test Results (FAILED) ===
FAIL: test_isolation — config mutation leaks

=== Diagnosis ===
{"failure_type": "logic_error", "root_cause": "shallow copy insufficient"}







Fix the failing tests with minimal changes.
```

---

# 5. Variable Extraction Test

From `tests/test_prompt_registry.py`:

```python
def test_task_and_code_variables(self):
    from prompt_registry import load_prompt_registry, get_component
    load_prompt_registry()
    comp = get_component("task_and_code")
    assert "task" in comp.required_variables
    assert "code_files_block" in comp.required_variables
```

**Runtime result:** PASS.
**Actual value:** `comp.required_variables = frozenset({'code_files_block', 'task'})`

**Cross-validated:** AST extraction and regex `\{\{\s*(\w+)\s*\}\}` produce identical sorted lists for all 15 components (Section 2.3).

---

# 6. Failure Mode Verification

## 6.1 Missing Variable Behavior

**Action:** Render `task_and_code.j2` with `{"task": "some task"}` (missing `code_files_block`).

**Actual exception:**
```
TYPE: jinja2.exceptions.UndefinedError
MESSAGE: 'code_files_block' is undefined
```

Full traceback:
```
Traceback (most recent call last):
  File "<stdin>", line 120, in <module>
  File ".venv/.../jinja2/environment.py", line 1295, in render
    self.environment.handle_exception()
  File ".venv/.../jinja2/environment.py", line 942, in handle_exception
    raise rewrite_traceback_stack(source=source)
  File "<template>", line 3, in top-level template code
jinja2.exceptions.UndefinedError: 'code_files_block' is undefined
```

**Mechanism:** `StrictUndefined` mode in Jinja2 Environment constructor.

## 6.2 Registry Immutability

**Action:** Call `load_prompt_registry()` after it has already been called.

**Actual exception:**
```
TYPE: builtins.RuntimeError
MESSAGE: Prompt registry already loaded. Call load_prompt_registry() only once.
```

**Mechanism:** `_loaded` flag checked at function entry.

---

# 7. Invariant Compliance Checklist

### INV-01: No Control Flow in Templates

**PASS.**

Every `.j2` file was scanned line-by-line for 18 Jinja2 tag patterns: `{% if %}`, `{% else %}`, `{% elif %}`, `{% endif %}`, `{% for %}`, `{% endfor %}`, `{% macro %}`, `{% endmacro %}`, `{% block %}`, `{% endblock %}`, `{% set %}`, `{% call %}`, `{% filter %}`, `{% raw %}`, `{% include %}`, `{% import %}`, `{% extends %}`, and a catch-all `{% ... %}`.

Results:
```
PASS: cge_stage (0 tags in 11 lines)
PASS: classify_reasoning (0 tags in 55 lines)
PASS: evaluate_reasoning_blind (0 tags in 62 lines)
PASS: evaluate_reasoning_conditioned (0 tags in 65 lines)
PASS: leg_reduction (0 tags in 80 lines)
PASS: nudge_diagnostic (0 tags in 1 lines)
PASS: nudge_guardrail (0 tags in 3 lines)
PASS: nudge_reasoning (0 tags in 1 lines)
PASS: nudge_scm (0 tags in 15 lines)
PASS: output_instruction_v1 (0 tags in 15 lines)
PASS: output_instruction_v2 (0 tags in 13 lines)
PASS: repair_feedback (0 tags in 4 lines)
PASS: retry_analysis (0 tags in 5 lines)
PASS: retry_generation (0 tags in 20 lines)
PASS: task_and_code (0 tags in 3 lines)
TOTAL VIOLATIONS: 0
```

### INV-02: All Variables Declared via AST Extraction

**PASS.**

For all 15 components, `jinja2.meta.find_undeclared_variables(env.parse(raw_text))` was compared against independent regex extraction `re.findall(r'\{\{\s*(\w+)\s*\}\}', raw_text)`. All 15 produced identical sorted variable lists (`ast_eq_regex=True`). See Section 2.3.

### INV-03: Hash Computed on Raw Template Text

**PASS.**

For all 15 components, the hash was independently recomputed from the file on disk (`hashlib.sha256(file.read_text().encode()).hexdigest()[:16]`) and compared against the registered hash. All 15 matched:

```
cge_stage: file=4fcf4f1910a8f0d6 reg=4fcf4f1910a8f0d6 match=True
classify_reasoning: file=ba5313c973c79a81 reg=ba5313c973c79a81 match=True
evaluate_reasoning_blind: file=c23d09f98ed2f514 reg=c23d09f98ed2f514 match=True
evaluate_reasoning_conditioned: file=d54dc4df02e715d2 reg=d54dc4df02e715d2 match=True
leg_reduction: file=994e91d022c36e8f reg=994e91d022c36e8f match=True
nudge_diagnostic: file=bb74b539f1976dd2 reg=bb74b539f1976dd2 match=True
nudge_guardrail: file=4984e04176db400d reg=4984e04176db400d match=True
nudge_reasoning: file=6fb447f4f340b699 reg=6fb447f4f340b699 match=True
nudge_scm: file=93cf07facc120aee reg=93cf07facc120aee match=True
output_instruction_v1: file=758d8951fe2ccb1a reg=758d8951fe2ccb1a match=True
output_instruction_v2: file=75c5d27de2670cf0 reg=75c5d27de2670cf0 match=True
repair_feedback: file=b9004e39a22986be reg=b9004e39a22986be match=True
retry_analysis: file=8086474e6e3ff0d9 reg=8086474e6e3ff0d9 match=True
retry_generation: file=2ca949f60bad4188 reg=2ca949f60bad4188 match=True
task_and_code: file=b5c11d4cbc063095 reg=b5c11d4cbc063095 match=True
```

### INV-04: Rendering Fails on Missing Variables

**PASS.**

Demonstrated in Section 6.1. `jinja2.exceptions.UndefinedError` raised with variable name in message.

### INV-05: Registry is Immutable After Load

**PASS.**

Demonstrated in Section 6.2. `RuntimeError` raised on second `load_prompt_registry()` call. `PromptComponent` uses `@dataclass(frozen=True)`.

### INV-06: No Implicit Composition Logic in Registry

**PASS.**

Registry exposes only: `get_component(name)`, `get_nudge_text(key)`, `get_cge_instruction(key)`, `get_all_components()`, `get_all_hashes()`, `is_loaded()`. No function combines, concatenates, orders, or renders components.

---

# 8. Content Equivalence — All 25 Nudge Texts

Every nudge text in `registry.yaml` was compared against its source Python string at runtime. Result:

```
diagnostic__hidden_dependency:        MATCH (src=1069, reg=1069)
diagnostic__temporal_causal_error:    MATCH (src=669, reg=669)
diagnostic__invariant_violation:      MATCH (src=694, reg=694)
diagnostic__state_semantic_violation: MATCH (src=717, reg=717)
guardrail__hidden_dependency:         MATCH (src=903, reg=903)
guardrail__temporal_causal_error:     MATCH (src=936, reg=936)
guardrail__invariant_violation:       MATCH (src=956, reg=956)
guardrail__state_semantic_violation:  MATCH (src=1061, reg=1061)
diagnostic__generic_dependency:       MATCH (src=784, reg=784)
diagnostic__generic_invariant:        MATCH (src=784, reg=784)
diagnostic__generic_temporal:         MATCH (src=848, reg=848)
diagnostic__generic_state:            MATCH (src=870, reg=870)
guardrail__generic_dependency:        MATCH (src=805, reg=805)
guardrail__generic_invariant:         MATCH (src=867, reg=867)
guardrail__generic_temporal:          MATCH (src=869, reg=869)
guardrail__generic_state:             MATCH (src=879, reg=879)
reasoning__counterfactual:            MATCH (src=746, reg=746)
reasoning__reason_then_act:           MATCH (src=664, reg=664)
reasoning__self_check:                MATCH (src=830, reg=830)
reasoning__counterfactual_check:      MATCH (src=642, reg=642)
reasoning__test_driven:               MATCH (src=756, reg=756)
reasoning__structured:                MATCH (src=298, reg=298)
reasoning__free_form:                 MATCH (src=87, reg=87)
reasoning__branching:                 MATCH (src=408, reg=408)
reasoning__alignment_extra:           MATCH (src=275, reg=275)
TOTAL: 25 checked, ALL_MATCH=True
```

**Comparison method:** `source_string == registry_string` (Python `==` operator, exact byte equality after YAML deserialization).

---

# 9. Known Risks / Unverified Areas

### R1: registry.yaml Has No Schema Validation

`yaml.safe_load()` with no structural validation. A misspelled top-level key (e.g., `nudge_txts`) would be silently ignored.

**Status:** UNVERIFIED. No startup check validates expected keys exist.

### R2: Missing Component Directory Produces Empty Registry

If `prompts/components/` does not exist, `load_prompt_registry()` succeeds with zero components.

**Status:** UNVERIFIED. No test for this case.

### R3: No Cross-Reference Between Components and registry.yaml

The nudge components (`nudge_diagnostic.j2`) expect variables like `diagnostic_text` that come from `registry.yaml` nudge entries. There is no validation that these cross-references are satisfiable.

**Status:** UNVERIFIED. Phase 2 (AssemblyEngine) responsibility.

### R4: `_reset_for_testing()` Breaks Immutability

Exists for test fixtures. Not called in production. Named with leading underscore.

**Status:** Acceptable. Low risk.

### R5: YAML Round-Trip Whitespace

YAML serialization may normalize whitespace in multi-line strings differently than Python source. The runtime equivalence check (Section 8) confirms byte equality after deserialization, but the YAML file itself may not be byte-identical to the Python source if inspected as raw text.

**Status:** LOW risk. Runtime equivalence is what matters for correctness.

---

*End of audit document. All evidence from runtime execution dated 2026-03-27.*
