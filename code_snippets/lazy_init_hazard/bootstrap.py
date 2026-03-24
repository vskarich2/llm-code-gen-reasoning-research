from config import override_settings, reset, get_settings


def init_app(env="production"):
    reset()
    if env == "production":
        override_settings({"timeout": 5, "retries": 1, "debug": False})
    elif env == "development":
        override_settings({"timeout": 60, "retries": 10, "debug": True})


def get_current_env():
    cfg = get_settings()
    return "development" if cfg.get("debug") else "production"
