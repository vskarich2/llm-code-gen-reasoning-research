def on_user_login(payload):
    return {
        "action": "login",
        "user": payload.get("user_id"),
        "session_timeout": 3600,
        "require_2fa": False,
    }


def on_admin_login(payload):
    return {
        "action": "admin_login",
        "user": payload.get("user_id"),
        "session_timeout": 900,
        "require_2fa": True,
    }


def on_logout(payload):
    return {
        "action": "logout",
        "user": payload.get("user_id"),
        "session_timeout": 0,
        "require_2fa": False,
    }
