"""Загрузка справочника УК в базу из csv или json.

    python -m app.parser --load data/companies.csv
    python -m app.parser --load parser_output/nsk.json

Повторный запуск ничего не дублирует: компания ищется по паре
«название + город», дом — по компании, городу, улице, номеру и
корпусу. Новые контакты и адреса при этом обновляются.
"""
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyHouse, ManagementCompany
from app.services.addresses import parse_house_list


@dataclass
class LoadResult:
    """Что получилось загрузить."""

    companies: int = 0
    houses: int = 0
    updated: int = 0


def load_file(db: Session, path: Path) -> LoadResult:
    """Загружает справочник из файла, формат определяется по расширению."""
    if path.suffix.lower() == ".json":
        return load_json(db, path)
    return load_csv(db, path)


def load_csv(db: Session, path: Path) -> LoadResult:
    """Справочник в формате data/companies.csv."""
    result = LoadResult()
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if _upsert_company(db, row, result):
                continue
            for house_number, house_corpus in parse_house_list(row.get("houses") or ""):
                _add_house(db, row, house_number, house_corpus, result)
    db.commit()
    return result


def load_json(db: Session, path: Path) -> LoadResult:
    """Справочник, выгруженный парсером: дома отдельными объектами."""
    result = LoadResult()
    companies = json.loads(path.read_text(encoding="utf-8"))
    for item in companies:
        row = {
            "name": item.get("name", ""),
            "email": item.get("email", ""),
            "phone": item.get("phone", ""),
            "website": item.get("website", ""),
            "city": item.get("city", ""),
        }
        if _upsert_company(db, row, result):
            continue
        for house in item.get("houses", []):
            number = house.get("number")
            if not isinstance(number, int):
                continue
            _add_house(db, {**row, "street": house.get("street", "")}, number, house.get("corpus"), result)
    db.commit()
    return result


def _upsert_company(db: Session, row: dict[str, str], result: LoadResult) -> bool:
    """Создаёт или обновляет компанию. True — если такой уже был."""
    name = (row.get("name") or "").strip()
    city = (row.get("city") or "").strip()
    email = (row.get("email") or "").strip()
    if not name or not city:
        return True
    if not email:
        # поле email в таблице обязательное, а отправлять обращение
        # некуда: оставляем заведомый адрес-заглушку по ОГРН
        email = "noreply@gis.jkh"

    company = db.scalar(
        select(ManagementCompany).where(
            ManagementCompany.name == name,
            ManagementCompany.city == city,
        )
    )
    if company is None:
        db.add(
            ManagementCompany(
                name=name,
                email=email,
                phone=(row.get("phone") or "").strip() or None,
                website=(row.get("website") or "").strip() or None,
                city=city,
            )
        )
        db.flush()
        result.companies += 1
        return False

    changed = _apply_contacts(company, row, email)
    if changed:
        result.updated += 1
    return False


def _apply_contacts(company: ManagementCompany, row: dict[str, str], email: str) -> bool:
    """Дополняет пустые контакты, не затирая уже заведённые."""
    changed = False
    updates = {
        "email": email,
        "phone": (row.get("phone") or "").strip() or None,
        "website": (row.get("website") or "").strip() or None,
    }
    for field, value in updates.items():
        if value and not getattr(company, field):
            setattr(company, field, value)
            changed = True
    return changed


def _add_house(
    db: Session,
    row: dict[str, str],
    house_number: int,
    house_corpus: str | None,
    result: LoadResult,
) -> None:
    street = (row.get("street") or "").strip()
    if not street:
        return
    company = db.scalar(
        select(ManagementCompany).where(
            ManagementCompany.name == (row.get("name") or "").strip(),
            ManagementCompany.city == (row.get("city") or "").strip(),
        )
    )
    if company is None:
        return
    exists = db.scalar(
        select(CompanyHouse).where(
            CompanyHouse.company_id == company.id,
            CompanyHouse.city == company.city,
            CompanyHouse.street == street,
            CompanyHouse.house_number == house_number,
            CompanyHouse.house_corpus == house_corpus,
        )
    )
    if exists is not None:
        return
    db.add(
        CompanyHouse(
            company_id=company.id,
            city=company.city,
            street=street,
            house_number=house_number,
            house_corpus=house_corpus,
        )
    )
    result.houses += 1
