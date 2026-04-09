_repo = {}
_repo_versions = {}


def clear_repo():
    global _repo, _repo_versions
    _repo = {}
    _repo_versions = {}


def create_user(user_id, display_name):
    _repo[user_id] = {"user_id": user_id, "display_name": display_name}
    _repo_versions[user_id] = 1
    return get_profile(user_id)


def update_display_name(user_id, new_name):
    if user_id not in _repo:
        raise KeyError(f"User {user_id} not found")
    _repo[user_id]["display_name"] = new_name
    _repo_versions[user_id] = _repo_versions.get(user_id, 0) + 1
    return get_profile(user_id)

def get_profile(user_id):
    if user_id not in _repo:
        return None
    return {
        "user_id": user_id,
        "display_name": _repo[user_id]["display_name"],
        "version": _repo_versions[user_id],
    }


def get_repo_version(user_id):
    return _repo_versions.get(user_id, 0)
