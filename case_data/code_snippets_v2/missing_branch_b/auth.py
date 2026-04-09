

from roles import admin_access, user_access, moderator_access, guest_access



_ROLE_DISPATCH = {
    "admin": admin_access,
    "user": user_access,
    "moderator": moderator_access,
}


def _default_access():

    return {"read": False, "write": False, "delete": False}


def get_access(role):

    handler = _ROLE_DISPATCH.get(role, _default_access)
    return handler()


def can_read(role):

    return get_access(role).get("read", False)
