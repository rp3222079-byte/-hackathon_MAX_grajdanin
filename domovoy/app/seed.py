"""Загрузка демо-данных: управляющие компании и отключения.

    python -m app.seed              # УК + отключения
    python -m app.seed --clear      # очистить отключения и уведомления
    python -m app.seed --companies  # только справочник УК
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import ManagementCompany, Notification, Outage, OutageArea, ServedHouse, UtilityType
from app.services.addresses import expand_house_range, normalize_house, normalize_street
from app.services.outages import create_outage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("domovoy.seed")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_companies() -> int:
    """Загружает справочник УК из data/companies.csv."""
    path = DATA_DIR / "companies.csv"
    if not path.exists():
        logger.warning("Нет файла %s", path)
        return 0

    db = SessionLocal()
    added = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                company = db.execute(
                    select(ManagementCompany).where(ManagementCompany.name == row["name"])
                ).scalar_one_or_none()

                if company is None:
                    company = ManagementCompany(
                        name=row["name"],
                        email=row["email"],
                        phone=row.get("phone") or None,
                        website=row.get("website") or None,
                        city=row.get("city") or settings.default_city,
                    )
                    db.add(company)
                    db.flush()

                street_key = normalize_street(row["street"])
                for chunk in row["houses"].split(","):
                    for house in expand_house_range(chunk.strip()):
                        house_key = normalize_house(house)
                        if not house_key:
                            continue
                        exists = db.execute(
                            select(ServedHouse).where(
                                ServedHouse.company_id == company.id,
                                ServedHouse.street_key == street_key,
                                ServedHouse.house_key == house_key,
                            )
                        ).scalar_one_or_none()
                        if exists:
                            continue
                        db.add(
                            ServedHouse(
                                company_id=company.id, street_key=street_key, house_key=house_key
                            )
                        )
                        added += 1
        db.commit()
    finally:
        db.close()

    logger.info("Домов закреплено за УК: %s", added)
    return added


def load_outages() -> int:
    """Загружает демо-отключения из data/mock_outages.json."""
    path = DATA_DIR / "mock_outages.json"
    if not path.exists():
        logger.warning("Нет файла %s", path)
        return 0

    items = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    created_count = 0
    try:
        for item in items:
            starts_at = now + timedelta(hours=item["starts_in_hours"])
            ends_at = starts_at + timedelta(hours=item["duration_hours"])
            _, created = create_outage(
                db,
                utility=UtilityType(item["utility"]),
                raw_addresses=item["raw_addresses"],
                starts_at=starts_at,
                ends_at=ends_at,
                reason=item.get("reason"),
                is_planned=item.get("is_planned", True),
                source="demo",
            )
            created_count += int(created)
    finally:
        db.close()

    logger.info("Демо-отключений добавлено: %s", created_count)
    return created_count


def clear_outages() -> None:
    """Удаляет отключения и отметки об уведомлениях — перед репетицией демо."""
    db = SessionLocal()
    try:
        db.execute(delete(Notification))
        db.execute(delete(OutageArea))
        db.execute(delete(Outage))
        db.commit()
    finally:
        db.close()
    logger.info("Отключения и уведомления очищены")


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо-данные сервиса «Домовой»")
    parser.add_argument("--clear", action="store_true", help="Очистить отключения и уведомления")
    parser.add_argument("--companies", action="store_true", help="Загрузить только справочник УК")
    arguments = parser.parse_args()

    init_db()
    if arguments.clear:
        clear_outages()
        return

    load_companies()
    if not arguments.companies:
        load_outages()


if __name__ == "__main__":
    main()
