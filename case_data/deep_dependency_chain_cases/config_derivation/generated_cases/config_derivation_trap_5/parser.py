def parse_config(env):
    return {
        "host": env["HOST"],
        "port": env["PORT"],
        "port_int": int(env["PORT"]),
        "max_conn": int(env["MAX_CONN"]),
        "debug": env["DEBUG"].lower() == "true",
    }
