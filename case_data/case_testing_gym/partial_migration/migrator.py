from schema import get_schema, set_schema, get_rows, set_rows, get_version


def migrate_add_role():
    """Add 'role' field to schema and backfill existing rows with default.

    Requirements:
    1. Add 'role' to schema fields
    2. Backfill all existing rows with role='member'
    3. Bump schema version to 2
    """
    schema = get_schema()

    # BUG: only updates schema fields, forgets to backfill rows and bump version
    if "role" not in schema["fields"]:
        schema["fields"].append("role")
        set_schema(schema)

    # Missing: backfill existing rows with role='member'
    # Missing: bump version to 2


def rollback():
    """Rollback the migration."""
    schema = get_schema()
    if "role" in schema["fields"]:
        schema["fields"].remove("role")
        set_schema(schema)
    rows = get_rows()
    for row in rows:
        row.pop("role", None)
    set_rows(rows)
    schema = get_schema()
    schema["version"] = 1
    set_schema(schema)


def check_migration_status():
    schema = get_schema()
    rows = get_rows()
    has_field = "role" in schema["fields"]
    rows_have_role = all("role" in r for r in rows)
    version_bumped = schema["version"] >= 2
    return {
        "schema_has_role": has_field,
        "rows_have_role": rows_have_role,
        "version_bumped": version_bumped,
        "complete": has_field and rows_have_role and version_bumped,
    }
