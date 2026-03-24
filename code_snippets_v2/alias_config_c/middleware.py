from config import create_config


class ConfigMiddleware:
    """Middleware that loads config once and applies per-request overrides."""

    def __init__(self):
        self._base = create_config()  # cached at init time

    def apply_config(self, request_overrides=None):
        """Return config for this request, applying any overrides."""
        cfg = self._base
        if request_overrides:
            cfg.update(request_overrides)  # mutates the cached reference
        return cfg

    def get_timeout(self):
        return self._base.get("timeout", 30)
