from data import PERMISSIONS, USER_DB

def resolve_permissions_node(normalized):
    key = f"{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        for prefix in ["ORG-", "DEPT-"]:
            test_key = f"{prefix}{normalized['org_id']}:{normalized['user']}"
            record = USER_DB.get(test_key)
            if record:
                break
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}
