from data import PERMISSIONS, USER_DB

def resolve_permissions_node(normalized):
    org_id = normalized.get("canonical_org_id", normalized["org_id"])
    key = f"{org_id}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}
