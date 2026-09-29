"""Отслеживание смены статуса обращений — временное хранилище в памяти.
Когда появится таблица в БД, замени _last_status на запрос к ней."""

_last_status = {}   # number -> status, последний статус, который мы уже показали жильцу


def check_changes(user_id, appeals):
    """appeals — список обращений жильца из API (api.list_appeals).
    Возвращает список (number, new_status) для тех, что реально изменились."""
    changes = []
    for appeal in appeals:
        number = appeal["number"]
        status = appeal["status"]
        previous = _last_status.get(number)
        if previous is not None and previous != status:
            changes.append((number, status))
        _last_status[number] = status
    return changes
