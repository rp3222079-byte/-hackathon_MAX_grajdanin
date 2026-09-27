"""Загрузка демо-данных: управляющие компании и отключения.

    python -m app.seed              # УК + отключения
    python -m app.seed --clear      # очистить отключения и уведомления
    python -m app.seed --companies  # только справочник УК
"""
import argparse
import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import (
    UTILITY_TYPES,
    CompanyHouse,
    ManagementCompany,
    Outage,
    OutageNotification,
)
from app.services.addresses import parse_house_list

logger = logging.getLogger("domovoy.seed")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COMPANIES_PATH = DATA_DIR / "companies.csv"
OUTAGES_PATH = DATA_DIR / "mock_outages.json"

# Отключения из файла заводятся относительно текущего момента, поэтому
# повторный запуск без --clear плодит дубли: отсекаем совпадение по часу
SAME_OUTAGE_TOLERANCE = timedelta(hours=1)


def load_companies(db: Session) -> int:
    """Загружает справочник УК из data/companies.csv, возвращает число домов."""
    added = 0
    with COMPANIES_PATH.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            company = db.scalar(
                select(ManagementCompany).where(
                    ManagementCompany.name == row["name"],
                    ManagementCompany.city == row["city"],
                )
            )
            if company is None:
                company = ManagementCompany(
                    name=row["name"],
                    email=row["email"],
                    phone=row.get("phone") or None,
                    website=row.get("website") or None,
                    city=row["city"],
                )
                db.add(company)
                db.flush()

            if not row["houses"].strip():
                continue
            houses = sorted(
                parse_house_list(row["houses"]),
                key=lambda house: (house[0], house[1] or ""),
            )
            for house_number, house_corpus in houses:
                exists = db.scalar(
                    select(CompanyHouse).where(
                        CompanyHouse.company_id == company.id,
                        CompanyHouse.city == row["city"],
                        CompanyHouse.street == row["street"],
                        CompanyHouse.house_number == house_number,
                        CompanyHouse.house_corpus == house_corpus,
                    )
                )
                if exists:
                    continue
                db.add(
                    CompanyHouse(
                        company_id=company.id,
                        city=row["city"],
                        street=row["street"],
                        house_number=house_number,
                        house_corpus=house_corpus,
                    )
                )
                added += 1

    db.commit()
    logger.info("Компаний в справочнике: %s, домов закреплено: %s", _companies_count(db), added)
    return added


def load_outages(db: Session) -> int:
    """Загружает демо-отключения из data/mock_outages.json, возвращает их число."""
    items = json.loads(OUTAGES_PATH.read_text(encoding="utf-8"))
    now = datetime.now()
    created = 0

    for item in items:
        if item["utility"] not in UTILITY_TYPES:
            logger.warning("Неизвестный тип ресурса %s, пропускаем", item["utility"])
            continue

        starts_at = now + timedelta(hours=item["starts_in_hours"])
        ends_at = starts_at + timedelta(hours=item["duration_hours"])
        if _outage_exists(db, item, starts_at):
            continue

        db.add(
            Outage(
                utility=item["utility"],
                city=item["city"],
                street=item["street"],
                houses_raw=item["houses_raw"],
                starts_at=starts_at,
                ends_at=ends_at,
                source="demo",
                reason=item.get("reason"),
            )
        )
        created += 1

    db.commit()
    logger.info("Демо-отключений добавлено: %s", created)
    return created


def clear_outages(db: Session) -> int:
    """Удаляет отключения и отметки об уведомлениях — перед репетицией демо."""
    notifications = db.execute(delete(OutageNotification)).rowcount
    outages = db.execute(delete(Outage)).rowcount
    db.commit()
    logger.info("Удалено отключений: %s, отметок об уведомлениях: %s", outages, notifications)
    return outages


def _companies_count(db: Session) -> int:
    return len(db.scalars(select(ManagementCompany)).all())


def _outage_exists(db: Session, item: dict, starts_at: datetime) -> bool:
    existing = db.scalars(
        select(Outage).where(
            Outage.utility == item["utility"],
            Outage.city == item["city"],
            Outage.street == item["street"],
            Outage.houses_raw == item["houses_raw"],
        )
    ).all()
    return any(abs(row.starts_at - starts_at) <= SAME_OUTAGE_TOLERANCE for row in existing)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Демо-данные сервиса «Домовой»")
    parser.add_argument("--clear", action="store_true", help="Очистить отключения и уведомления")
    parser.add_argument("--companies", action="store_true", help="Загрузить только справочник УК")
    arguments = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if arguments.clear:
            clear_outages(db)
            return

        load_companies(db)
        if not arguments.companies:
            load_outages(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
