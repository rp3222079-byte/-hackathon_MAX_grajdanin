"""Чтение .env для процессов без pydantic-настроек (бот, почта).

API читает .env через app/config.py, а бот и отправка писем берут
переменные из os.environ. Чтобы локальный запуск `python -m app.bot.main`
работал так же, как в Docker, файл .env подгружается в окружение.
Уже заданные переменные не перезаписываются: окружение Docker главнее.
"""
import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
