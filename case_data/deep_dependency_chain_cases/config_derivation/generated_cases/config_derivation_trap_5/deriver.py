def derive_settings_node(parsed):
    port = parsed.get("port_int", parsed["port"])
    pool_size = port * 2
    listen_addr = f"{parsed['host']}:{port}"
    timeout = 5 if parsed["debug"] else 30
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed["max_conn"],
        "port": port,
    }
