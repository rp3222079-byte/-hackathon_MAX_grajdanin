"""Базовый класс парсера источника отключений."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.models import UtilityType

logger = logging.getLogger(__name__)


@dataclass
class ParsedOutage:
    """Одно отключение в том виде, в каком его вернул источник."""

    utility: UtilityType
    raw_addresses: str
    starts_at: datetime
    ends_at: datetime | None = None
    reason: str | None = None
    is_planned: bool = True
    city: str | None = None


class BaseParser(ABC):
    """Наследник должен уметь только одно: превратить HTML в список отключений."""

    source_name: str = "unknown"

    def __init__(self, url: str) -> None:
        self.url = url

    def fetch(self) -> str:
        """Скачивает страницу источника."""
        headers = {"User-Agent": "Domovoy/1.0 (+hackathon project)"}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
            response = client.get(self.url)
            response.raise_for_status()
            return response.text

    @abstractmethod
    def parse(self, html: str) -> list[ParsedOutage]:
        """Разбирает HTML в список отключений."""

    def run(self) -> list[ParsedOutage]:
        try:
            html = self.fetch()
        except Exception:  # noqa: BLE001 — источник может лежать
            logger.exception("Источник %s недоступен", self.url)
            return []
        try:
            return self.parse(html)
        except Exception:  # noqa: BLE001 — вёрстка могла поменяться
            logger.exception("Не удалось разобрать страницу %s", self.url)
            return []
