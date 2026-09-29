"""Текущее время в часовом поясе города.

В базе время хранится без пояса, как его показывает источник отключений:
«с 10:00 до 18:00» по местному времени. Поэтому и «сейчас» берём местное,
а не время сервера — в Docker это UTC, и отключения сдвинулись бы на 7 часов.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings


def local_now() -> datetime:
    """Местное время без пояса, с точностью до секунды."""
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None, microsecond=0)
