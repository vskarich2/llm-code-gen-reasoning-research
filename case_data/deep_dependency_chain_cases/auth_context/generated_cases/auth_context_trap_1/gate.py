def check_gate_node(resolved):
    required = resolved.get("required_permission", "read")
    granted = required in resolved["permissions"]
    if not granted and resolved["tier"] == "default":
        granted = True
    return {"granted": granted, "tier": resolved["tier"],
            "org_id": resolved["org_id"], "user": resolved["user"],
            "required_permission": required}
