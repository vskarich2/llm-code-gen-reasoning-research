def admin_access():
    return {"read": True, "write": True, "delete": True}

def user_access():
    return {"read": True, "write": True, "delete": False}

def moderator_access():
    return {"read": True, "write": False, "delete": True}

def guest_access():
    return {"read": True, "write": False, "delete": False}
