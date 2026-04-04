from events import register, emit
from handlers import on_user_login, on_admin_login, on_logout


def setup():
    register("user_login", on_user_login)
    # BUG: admin_login should use on_admin_login, not on_user_login
    register("admin_login", on_user_login)
    register("logout", on_logout)


def handle_login(user_id, is_admin=False):
    event_type = "admin_login" if is_admin else "user_login"
    return emit(event_type, {"user_id": user_id})


def handle_logout(user_id):
    return emit("logout", {"user_id": user_id})
