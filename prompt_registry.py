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


# Module-level registry (populated by load_prompt_registry, frozen after)
_components: dict[str, PromptComponent] = {}
_nudge_texts: dict[str, str] = {}
_cge_instructions: dict[str, str] = {}
_loaded: bool = False


def load_prompt_registry() -> dict[str, PromptComponent]:
    """Load all components and registry entries. Called once at startup.

    Returns dict of component_name -> PromptComponent.
    Also populates nudge_texts and cge_instructions from registry.yaml.
    """
    global _components, _nudge_texts, _cge_instructions, _loaded

    if _loaded:
        raise RuntimeError("Prompt registry already loaded. Call load_prompt_registry() only once.")

    # Load .j2 component files
    env = Environment(
        loader=FileSystemLoader(str(COMPONENTS_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    components = {}
    if COMPONENTS_DIR.exists():
        for j2_file in sorted(COMPONENTS_DIR.glob("*.j2")):
            name = j2_file.stem  # e.g., "task_and_code"
            raw_text = j2_file.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

            # Extract required variables from Jinja2 AST
            parsed = env.parse(raw_text)
            variables = meta.find_undeclared_variables(parsed)

            components[name] = PromptComponent(
                name=name,
                source_path=str(j2_file.relative_to(BASE_DIR)),
                raw_text=raw_text,
                content_hash=content_hash,
                required_variables=frozenset(variables),
            )

    # Load registry.yaml (nudge texts, CGE instructions)
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

    _log.info(
        "Prompt registry loaded: %d components, %d nudge texts, %d CGE instructions",
        len(components),
        len(nudge_texts),
        len(cge_instructions),
    )
    return components


def get_component(name: str) -> PromptComponent:
    """Get a component by name. Fatal if not found."""
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded. Call load_prompt_registry() first.")
    if name not in _components:
        raise KeyError(
            f"REGISTRY ERROR: Component '{name}' not found. "
            f"Available: {sorted(_components.keys())}"
        )
    return _components[name]


def get_nudge_text(key: str) -> str:
    """Get a nudge text entry by key. Fatal if not found."""
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    if key not in _nudge_texts:
        raise KeyError(
            f"REGISTRY ERROR: Nudge text '{key}' not found. "
            f"Available: {sorted(_nudge_texts.keys())}"
        )
    return _nudge_texts[key]


def get_cge_instruction(key: str) -> str:
    """Get a CGE instruction entry by key. Fatal if not found."""
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    if key not in _cge_instructions:
        raise KeyError(
            f"REGISTRY ERROR: CGE instruction '{key}' not found. "
            f"Available: {sorted(_cge_instructions.keys())}"
        )
    return _cge_instructions[key]


def get_all_components() -> dict[str, PromptComponent]:
    """Return all loaded components."""
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    return dict(_components)


def get_all_hashes() -> dict[str, str]:
    """Return {component_name: content_hash} for all components."""
    if not _loaded:
        raise RuntimeError("Prompt registry not loaded.")
    return {name: c.content_hash for name, c in _components.items()}


def is_loaded() -> bool:
    """Check if registry has been loaded."""
    return _loaded


def _reset_for_testing():
    """Reset registry state. ONLY for test fixtures."""
    global _components, _nudge_texts, _cge_instructions, _loaded
    _components = {}
    _nudge_texts = {}
    _cge_instructions = {}
    _loaded = False
