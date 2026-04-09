def parse_token(token):
    return {"org_id": token["org_id"], "user": token["user"], "action": token["action"],
            "required_permission": token.get("required_permission", "read")}
