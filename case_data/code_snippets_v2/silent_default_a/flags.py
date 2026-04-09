FLAGS = {
    "dark_mode": True,
    "beta_features": False,
    "new_dashboard": True,
    "analytics_v2": False,
}

def is_enabled(flag_name):
    return FLAGS.get(flag_name, False)

def list_flags():
    return list(FLAGS.keys())
