"""Section marker parser.

State-machine parser (not regex) that extracts typed sections from
rendered prompt output. Validates marker pairing, nesting, naming,
and content-outside-sections.

Marker syntax:
    <<SECTION:section_name>>
    ...content...
    <<END_SECTION:section_name>>

Markers must appear at column 0 (start of line, ignoring leading whitespace).
"""

from __future__ import annotations

from core.pipeline.prompting.contracts import ParsedSection
from core.pipeline.prompting.sections import Section, VALID_SECTION_VALUES

_MARKER_START_PREFIX = "<<SECTION:"
_MARKER_END_PREFIX = "<<END_SECTION:"
_MARKER_SUFFIX = ">>"


def strip_markers(rendered: str) -> str:
    """Remove all section marker lines from rendered output.

    Returns the content with marker lines removed, preserving all other
    content and whitespace exactly. This ensures byte equivalence between
    marked and unmarked templates when only the marker lines differ.
    """
    lines = rendered.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if (stripped.startswith(_MARKER_START_PREFIX) and stripped.endswith(_MARKER_SUFFIX)):
            continue
        if (stripped.startswith(_MARKER_END_PREFIX) and stripped.endswith(_MARKER_SUFFIX)):
            continue
        out.append(line)
    return "\n".join(out)


def parse_sections(rendered: str) -> tuple[list[ParsedSection], list[str]]:
    """Parse rendered output into structural sections.

    Returns:
        (sections, errors) where errors are structural violations.
        Caller decides severity based on compiler mode.
    """
    sections: list[ParsedSection] = []
    errors: list[str] = []
    lines = rendered.split("\n")

    current_section: str | None = None
    current_content: list[str] = []
    current_start: int = -1

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check for start marker
        if stripped.startswith(_MARKER_START_PREFIX) and stripped.endswith(_MARKER_SUFFIX):
            # Column-0 enforcement: marker must be at start of line
            # (after stripping only whitespace, not other content)
            leading_non_ws = line.lstrip()
            if leading_non_ws != stripped:
                errors.append(
                    f"Line {i + 1}: marker not at column 0: '{stripped[:60]}'"
                )
                continue

            section_name = stripped[len(_MARKER_START_PREFIX):-len(_MARKER_SUFFIX)]

            # Validate against Section enum
            if section_name not in VALID_SECTION_VALUES:
                errors.append(
                    f"Line {i + 1}: unknown section '{section_name}'. "
                    f"Valid: {sorted(VALID_SECTION_VALUES)}"
                )
                continue

            if current_section is not None:
                errors.append(
                    f"Line {i + 1}: nested section '{section_name}' "
                    f"inside open section '{current_section}'"
                )
                continue

            current_section = section_name
            current_start = i + 1
            current_content = []

        # Check for end marker
        elif stripped.startswith(_MARKER_END_PREFIX) and stripped.endswith(_MARKER_SUFFIX):
            end_name = stripped[len(_MARKER_END_PREFIX):-len(_MARKER_SUFFIX)]

            if current_section is None:
                errors.append(
                    f"Line {i + 1}: END_SECTION '{end_name}' without matching start"
                )
                continue

            if end_name != current_section:
                errors.append(
                    f"Line {i + 1}: END_SECTION '{end_name}' does not match "
                    f"open section '{current_section}'"
                )
                continue

            sections.append(ParsedSection(
                name=Section(current_section),
                content="\n".join(current_content),
                start_line=current_start,
                end_line=i,
            ))
            current_section = None
            current_content = []

        else:
            if current_section is not None:
                # Check for marker injection inside content
                if _MARKER_START_PREFIX in line or _MARKER_END_PREFIX in line:
                    errors.append(
                        f"Line {i + 1}: marker-like syntax inside section "
                        f"'{current_section}' content"
                    )
                current_content.append(line)
            else:
                # Text outside any section
                if stripped:
                    errors.append(
                        f"Line {i + 1}: non-whitespace content outside any section: "
                        f"'{stripped[:80]}'"
                    )

    if current_section is not None:
        errors.append(
            f"Unclosed section '{current_section}' starting at line {current_start}"
        )

    return sections, errors


def reconstruct_from_sections(
    parsed_sections: list[ParsedSection],
    section_order: tuple[Section, ...],
) -> str:
    """Reconstruct final prompt from parsed sections in program-defined order.

    Sections are ordered according to section_order. Sections not in
    section_order are appended at the end in parse order.
    """
    section_map: dict[Section, list[ParsedSection]] = {}
    for s in parsed_sections:
        section_map.setdefault(s.name, []).append(s)

    ordered_parts: list[str] = []
    used_sections: set[Section] = set()

    # Emit sections in program-defined order
    for section in section_order:
        if section in section_map:
            for s in section_map[section]:
                ordered_parts.append(s.content)
            used_sections.add(section)

    # Append any remaining sections not in section_order (in parse order)
    for s in parsed_sections:
        if s.name not in used_sections:
            ordered_parts.append(s.content)

    return "".join(ordered_parts)
