"""Запуск парсера: разово или по расписанию.

Разово:        python -m app.parser.runner --once
По расписанию: python -m app.parser.runner
"""
from __future__ import annotations

import argparse
import logging
import time

from app.config import settings
from app.db import SessionLocal, init_db
from app.parser.site import SiteParser
from app.services.outages import create_outage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("domovoy.parser")


def run_once() -> int:
    """Собирает отключения с источника. Возвращает число новых записей."""
    if not settings.parser_source_url:
        logger.warning("PARSER_SOURCE_URL не задан — парсер простаивает")
        return 0

    parser = SiteParser(settings.parser_source_url)
    parsed = parser.run()
    if not parsed:
        return 0

    created_count = 0
    db = SessionLocal()
    try:
        for item in parsed:
            _, created = create_outage(
                db,
                utility=item.utility,
                raw_addresses=item.raw_addresses,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                reason=item.reason,
                is_planned=item.is_planned,
                source=settings.parser_source_url,
                city=item.city,
            )
            created_count += int(created)
    finally:
        db.close()

    logger.info("Новых отключений: %s из %s полученных", created_count, len(parsed))
    return created_count


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Сбор отключений с сайта-источника")
    argument_parser.add_argument("--once", action="store_true", help="Один проход и выход")
    arguments = argument_parser.parse_args()

    init_db()
    if arguments.once:
        run_once()
        return

    logger.info("Парсер запущен, интервал %s секунд", settings.parser_interval_seconds)
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001 — цикл не должен останавливаться
            logger.exception("Ошибка в проходе парсера")
        time.sleep(settings.parser_interval_seconds)


if __name__ == "__main__":
    main()
