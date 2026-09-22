"""Парсер сайта-источника отключений.

Это рабочий шаблон под таблицу вида:

    <table class="outages">
      <tr>
        <td>Холодная вода</td>
        <td>ул. Ленина, 1-15</td>
        <td>14.06.2026 09:00</td>
        <td>14.06.2026 18:00</td>
        <td>Плановые работы</td>
      </tr>
    </table>

Под свой сайт меняйте только селекторы в ROW_SELECTOR и COLUMNS
и, при необходимости, формат даты в DATE_FORMATS.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.config import settings
from app.models import UtilityType
from app.parser.base import BaseParser, ParsedOutage

logger = logging.getLogger(__name__)

ROW_SELECTOR = "table.outages tr"
COLUMNS = {"utility": 0, "addresses": 1, "starts_at": 2, "ends_at": 3, "reason": 4}
DATE_FORMATS = ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S")

UTILITY_KEYWORDS = (
    (("горяч", "гвс"), UtilityType.WATER_HOT),
    (("холодн", "хвс", "водоснаб", "вода"), UtilityType.WATER_COLD),
    (("электр", "свет", "энерг"), UtilityType.ELECTRICITY),
    (("отоплен", "тепло"), UtilityType.HEATING),
    (("газ",), UtilityType.GAS),
)
EMERGENCY_WORDS = ("аварий", "внеплан", "неотложн")


def guess_utility(text: str) -> UtilityType | None:
    """Определяет тип ресурса по словам в ячейке."""
    lowered = (text or "").lower()
    for keywords, utility in UTILITY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return utility
    return None


def parse_datetime(value: str) -> datetime | None:
    """Разбирает дату в любом из известных форматов."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            local = datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo(settings.timezone))
            return local.astimezone(timezone.utc)
        except ValueError:
            continue
    logger.debug("Не разобрал дату: %r", text)
    return None


class SiteParser(BaseParser):
    source_name = "site"

    def parse(self, html: str) -> list[ParsedOutage]:
        soup = BeautifulSoup(html, "lxml")
        outages: list[ParsedOutage] = []

        for row in soup.select(ROW_SELECTOR):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) <= max(COLUMNS.values()):
                continue  # шапка таблицы или пустая строка

            utility = guess_utility(cells[COLUMNS["utility"]])
            starts_at = parse_datetime(cells[COLUMNS["starts_at"]])
            addresses = cells[COLUMNS["addresses"]]
            if not utility or not starts_at or not addresses:
                continue

            reason = cells[COLUMNS["reason"]] if COLUMNS["reason"] < len(cells) else None
            outages.append(
                ParsedOutage(
                    utility=utility,
                    raw_addresses=addresses,
                    starts_at=starts_at,
                    ends_at=parse_datetime(cells[COLUMNS["ends_at"]]),
                    reason=reason,
                    is_planned=not any(word in (reason or "").lower() for word in EMERGENCY_WORDS),
                    city=settings.default_city,
                )
            )

        logger.info("Источник вернул %s отключений", len(outages))
        return outages
