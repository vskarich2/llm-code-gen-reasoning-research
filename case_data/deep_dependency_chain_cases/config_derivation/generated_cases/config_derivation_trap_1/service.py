def init_service_node(settings):
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str):
        pool_size = 16160
    elif pool_size > 20000:
        pool_size = 16160
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
    }
