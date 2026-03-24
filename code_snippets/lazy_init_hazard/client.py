from config import get_settings


def make_request(url, data=None):
    cfg = get_settings()
    timeout = cfg["timeout"]
    return {"url": url, "data": data, "timeout": timeout}


def make_debug_request(url):
    cfg = get_settings()
    if not cfg["debug"]:
        return None
    return make_request(url, data={"debug": True})
