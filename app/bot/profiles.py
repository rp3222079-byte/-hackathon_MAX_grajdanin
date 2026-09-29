_profiles = {}


def remember(user_id, name=None, username=None):
    _profiles[user_id] = {"name": name, "username": username}


def get(user_id):
    return _profiles.get(user_id)