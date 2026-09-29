"""Состояние диалога жильца: на каком шаге он и что уже ввёл.

Хранится в JSON-файле (BOT_STATE_PATH), чтобы перезапуск бота не
обрывал незаконченное обращение. Пишет в файл только поток приёма
сообщений, поэтому блокировок не нужно.
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("domovoy.bot")

_user_states: dict[str, dict] = {}
_loaded_from: Path | None = None


def _path() -> Path:
    return Path(os.getenv("BOT_STATE_PATH", "bot_state.json"))


def _ensure_loaded() -> None:
    global _loaded_from, _user_states
    path = _path()
    if _loaded_from == path:
        return
    _loaded_from = path
    _user_states = {}
    if path.is_file():
        try:
            _user_states = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Не удалось прочитать состояния диалогов %s: %s", path, error)


def _save() -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_user_states, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        # без файла бот продолжит работать, просто диалоги не переживут перезапуск
        logger.warning("Не удалось сохранить состояния диалогов: %s", error)


def get_state(user_id):
    """Текущее состояние: {"step": ..., "data": {...}} или None."""
    _ensure_loaded()
    return _user_states.get(str(user_id))


def set_state(user_id, step, data=None):
    """Перевести жильца на шаг step с данными data."""
    _ensure_loaded()
    _user_states[str(user_id)] = {"step": step, "data": data if data is not None else {}}
    _save()


def clear_state(user_id):
    """Завершить диалог."""
    _ensure_loaded()
    if _user_states.pop(str(user_id), None) is not None:
        _save()
