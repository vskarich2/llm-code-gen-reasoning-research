POLICIES = {
    "v1": {"version": "v1", "behavior": "legacy", "fallback": True},
    "v2": {"version": "v2", "behavior": "intermediate", "fallback": False},
    "v3": {"version": "v3", "behavior": "latest", "fallback": False},
}

def get_policy(version):
    return POLICIES.get(version)

def get_latest_version():

    return "v3"


def get_fallback_version():

    return "v1"
