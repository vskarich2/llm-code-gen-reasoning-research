"""Developer tools for the prompt compilation system.

generate_metadata_from_ast: produces draft component_metadata.yaml entries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from core.pipeline.prompting.metadata import generate_metadata_from_ast


def generate_command(component_name: str, components_dir: str = "core/prompts/components") -> None:
    """Generate draft metadata for a component and print as YAML."""
    template_path = Path(components_dir) / f"{component_name}.j2"
    if not template_path.exists():
        print(f"ERROR: {template_path} not found", file=sys.stderr)
        sys.exit(1)

    draft = generate_metadata_from_ast(template_path)
    print(f"# Draft metadata for {component_name}")
    print(f"# AUTO-GENERATED — review and correct before committing")
    print(f"{component_name}:")
    # Indent the yaml output under the component name
    yaml_str = yaml.dump(draft, default_flow_style=False, sort_keys=False)
    for line in yaml_str.splitlines():
        print(f"  {line}")


def generate_all_command(components_dir: str = "core/prompts/components") -> None:
    """Generate draft metadata for all components."""
    cdir = Path(components_dir)
    if not cdir.exists():
        print(f"ERROR: {cdir} not found", file=sys.stderr)
        sys.exit(1)

    print("# component_metadata.yaml — AUTO-GENERATED DRAFT")
    print("# Review ALL entries before committing.")
    print("# Pay special attention to: required vs optional, control_inputs, exports")
    print()

    for j2_file in sorted(cdir.glob("*.j2")):
        name = j2_file.stem
        draft = generate_metadata_from_ast(j2_file)
        print(f"{name}:")
        yaml_str = yaml.dump(draft, default_flow_style=False, sort_keys=False)
        for line in yaml_str.splitlines():
            print(f"  {line}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.prompting.tools generate <component_name>")
        print("       python -m pipeline.prompting.tools generate-all")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "generate" and len(sys.argv) >= 3:
        generate_command(sys.argv[2])
    elif cmd == "generate-all":
        generate_all_command()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
