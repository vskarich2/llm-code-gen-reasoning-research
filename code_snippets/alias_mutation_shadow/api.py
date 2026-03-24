from config import create_config
from defaults import DEFAULTS


def new_user_session(prefs=None):
    cfg = create_config(overrides=prefs, inherit=True)
    return {"config": cfg}
