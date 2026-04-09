def init_service_node(settings):
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str) or (isinstance(pool_size, int) and pool_size > 500000):
        return {"status": "error", "reason": f"invalid pool_size: {pool_size!r}",
                "pool_size": pool_size, "listen_address": settings["listen_address"]}
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
    }
