"""Загрузка демо-данных: управляющие компании и отключения.

    python -m app.seed              # УК + отключения
    python -m app.seed --clear      # очистить отключения и уведомления
    python -m app.seed --companies  # только справочник УК
"""
import argparse
import csv
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import (
    UTILITY_ELECTRICITY,
    UTILITY_TYPES,
    UTILITY_WATER,
    CompanyHouse,
    ManagementCompany,
    Outage,
    OutageNotification,
)
from app.services.addresses import parse_house_list

logger = logging.getLogger("domovoy.seed")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COMPANIES_PATH = DATA_DIR / "companies.csv"

# Отключения заводятся относительно текущего момента, поэтому
# повторный запуск без --clear плодит дубли: отсекаем совпадение по часу
SAME_OUTAGE_TOLERANCE = timedelta(hours=1)

OUTAGE_REASONS = {
    UTILITY_WATER: (
        "Плановая замена участка трубопровода",
        "Профилактическая промывка водопровода",
        "Замена запорной арматуры в подвале",
        "Устранение течи на водопроводной сети",
    ),
    UTILITY_ELECTRICITY: (
        "Плановый ремонт подстанции",
        "Ремонт участка линии электропередачи",
        "Аварийные работы на кабельной линии",
        "Замена опоры воздушной линии",
    ),
}
# Отрицательное значение означает, что работы уже идут
STARTS_IN_HOURS = (-1, 2, 5, 18, 30, 72)
DURATIONS_HOURS = (3, 4, 6, 8, 9)


def read_company_rows() -> list[dict[str, str]]:
    """Читает справочник УК из data/companies.csv."""
    with COMPANIES_PATH.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def demo_streets() -> list[tuple[str, str, str]]:
    """Город, улица и дома из справочника — по одной записи на улицу."""
    streets: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in read_company_rows():
        key = (row["city"], row["street"])
        if key in seen:
            continue
        seen.add(key)
        streets.append((row["city"], row["street"], row["houses"]))
    return streets


def demo_outage_params(street: str) -> tuple[str, str, int, int]:
    """Ресурс, причина, начало и длительность отключения — стабильно по улице."""
    generator = random.Random(street)
    utility = generator.choice(UTILITY_TYPES)
    reason = generator.choice(OUTAGE_REASONS[utility])
    starts_in_hours = generator.choice(STARTS_IN_HOURS)
    duration_hours = generator.choice(DURATIONS_HOURS)
    return utility, reason, starts_in_hours, duration_hours


def load_companies(db: Session) -> int:
    """Загружает справочник УК из data/companies.csv, возвращает число домов."""
    added = 0
    for row in read_company_rows():
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
    """Создаёт демо-отключение на каждую улицу справочника, возвращает их число."""
    now = datetime.now()
    created = 0

    for city, street, houses_raw in demo_streets():
        utility, reason, starts_in_hours, duration_hours = demo_outage_params(street)
        item = {
            "utility": utility,
            "city": city,
            "street": street,
            "houses_raw": houses_raw,
            "reason": reason,
        }
        starts_at = now + timedelta(hours=starts_in_hours)
        ends_at = starts_at + timedelta(hours=duration_hours)
        if _outage_exists(db, item, starts_at):
            continue

        db.add(
            Outage(
                utility=utility,
                city=city,
                street=street,
                houses_raw=houses_raw,
                starts_at=starts_at,
                ends_at=ends_at,
                source="demo",
                reason=reason,
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
