"""Имя и ник жильца в MAX: приходят с каждым сообщением, храним последние."""
_profiles = {}


def remember(user_id, name=None, username=None):
    _profiles[user_id] = {"name": name, "username": username}


def get(user_id):
    return _profiles.get(user_id)
