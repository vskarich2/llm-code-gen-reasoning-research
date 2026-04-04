"""Canonical prompt component and program registry.

Loads components from prompts/components/*.j2 with contracts from
component_metadata.yaml. Validates at load time: forbidden tags,
metadata-AST drift, version-hash consistency, cross-component
section constraints.

Immutable after load. Single instance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from core.pipeline.prompting.contracts import PromptComponent, PromptProgram
from core.pipeline.prompting.exceptions import (
    DuplicatePromptComponentError,
    PromptRegistryError,
    UnknownPromptComponentError,
)
from core.pipeline.prompting.metadata import (
    load_component_from_metadata,
    validate_control_inputs,
    validate_forbidden_tags,
    validate_template_against_metadata,
)
from core.pipeline.prompting.sections import SINGLETON_SECTIONS, Section

_log = logging.getLogger("t3.prompt_registry_v2")


class PromptRegistry:
    """Canonical registry for prompt components and programs.

    Load once at startup. Immutable after load.
    """

    def __init__(self) -> None:
        self._components: dict[str, PromptComponent] = {}
        self._programs: dict[str, PromptProgram] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(
        self,
        components_dir: Path,
        metadata_path: Path,
        manifest_path: Path | None = None,
        versions_path: Path | None = None,
        validate: bool = True,
    ) -> None:
        """Load all components and optionally programs from manifest.

        Args:
            components_dir: Directory containing *.j2 template files.
            metadata_path: Path to component_metadata.yaml.
            manifest_path: Optional path to prompt_manifest.yaml for programs.
            versions_path: Optional path to component_versions.json for
                version-hash drift detection.
            validate: If True, run full validation (forbidden tags, AST drift,
                control inputs). Set False only for testing.
        """
        if self._loaded:
            raise PromptRegistryError("Registry already loaded.")

        # Load metadata
        if not metadata_path.exists():
            raise PromptRegistryError(
                f"Component metadata not found: {metadata_path}"
            )
        raw_metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(raw_metadata, dict):
            raise PromptRegistryError(
                f"component_metadata.yaml must be a dict, got {type(raw_metadata)}"
            )

        # Load version registry if available
        version_registry: dict[str, dict[str, str]] = {}
        if versions_path and versions_path.exists():
            version_registry = json.loads(
                versions_path.read_text(encoding="utf-8")
            )

        # Load each component
        for j2_file in sorted(components_dir.glob("*.j2")):
            name = j2_file.stem

            if name in self._components:
                raise DuplicatePromptComponentError(
                    f"Duplicate component: '{name}'"
                )

            # Read template
            raw_template = j2_file.read_text(encoding="utf-8")

            # Style enforcement: controlled by validate flag
            if validate:
                validate_forbidden_tags(name, raw_template)

            # Get metadata entry
            meta_entry = raw_metadata.get(name)
            if meta_entry is None:
                raise PromptRegistryError(
                    f"Component '{name}' has no entry in "
                    f"component_metadata.yaml. Run: "
                    f"python -m pipeline.prompting.tools generate {name}"
                )

            # Build component from metadata
            comp = load_component_from_metadata(name, j2_file, meta_entry)

            # Contract enforcement: ALWAYS runs. Not optional.
            validate_template_against_metadata(comp)
            validate_control_inputs(comp)

            # Version-hash drift check
            if name in version_registry:
                recorded = version_registry[name]
                if (
                    recorded.get("version") == comp.version
                    and recorded.get("hash") != comp.content_hash
                ):
                    from core.pipeline.prompting.exceptions import PromptVersionDriftError
                    raise PromptVersionDriftError(
                        f"Component '{name}' version {comp.version}: "
                        f"content_hash changed from "
                        f"{recorded['hash'][:12]}... to "
                        f"{comp.content_hash[:12]}... "
                        f"Bump version in metadata."
                    )

            self._components[name] = comp

        _log.info(
            "Loaded %d components from %s",
            len(self._components), components_dir,
        )

        # Cross-component section validation
        if validate:
            self._validate_global_sections()

        # Load programs from manifest
        if manifest_path and manifest_path.exists():
            self._load_programs(manifest_path)

        self._loaded = True

    def _validate_global_sections(self) -> None:
        """Log warnings for singleton section conflicts across components."""
        section_owners: dict[Section, list[str]] = {}
        for comp in self._components.values():
            for section in comp.exports:
                section_owners.setdefault(section, []).append(comp.name)

        for section, owners in section_owners.items():
            if section in SINGLETON_SECTIONS and len(owners) > 1:
                _log.warning(
                    "Singleton section %s exported by multiple components: "
                    "%s. These cannot coexist in one program.",
                    section.value, owners,
                )

    def _load_programs(self, manifest_path: Path) -> None:
        """Load PromptPrograms from prompt_manifest.yaml."""
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        conditions = raw.get("conditions", {})

        for cond_name, spec in conditions.items():
            components = tuple(spec.get("components", []))
            # Programs are loaded permissively — unknown components are
            # caught at compile time, not load time, so legacy programs
            # don't break the registry.
            self._programs[cond_name] = PromptProgram(
                name=f"{cond_name}_program",
                condition=cond_name,
                components=components,
                required_sections=(),
                allowed_sections=tuple(Section),
                section_order=(),
                strict=False,
            )

    def get(self, name: str) -> PromptComponent:
        """Get a component by name. Fatal if not found."""
        if not self._loaded:
            raise PromptRegistryError("Registry not loaded.")
        if name not in self._components:
            raise UnknownPromptComponentError(
                f"Component '{name}' not found. "
                f"Available: {sorted(self._components.keys())}"
            )
        return self._components[name]

    def get_program(self, condition: str) -> PromptProgram:
        """Get a program by condition name."""
        if not self._loaded:
            raise PromptRegistryError("Registry not loaded.")
        if condition not in self._programs:
            raise PromptRegistryError(
                f"No program for condition '{condition}'. "
                f"Available: {sorted(self._programs.keys())}"
            )
        return self._programs[condition]

    def get_all_components(self) -> dict[str, PromptComponent]:
        if not self._loaded:
            raise PromptRegistryError("Registry not loaded.")
        return dict(self._components)

    def get_all_programs(self) -> dict[str, PromptProgram]:
        if not self._loaded:
            raise PromptRegistryError("Registry not loaded.")
        return dict(self._programs)

    def component_count(self) -> int:
        return len(self._components)

    def _reset_for_testing(self) -> None:
        """Reset state. Testing only."""
        self._components = {}
        self._programs = {}
        self._loaded = False
