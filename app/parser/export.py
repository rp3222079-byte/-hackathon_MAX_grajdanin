"""Выгрузка собранного справочника в csv и json.

Формат csv повторяет data/companies.csv, поэтому его читает и
существующий seed-загрузчик: одна строка — компания, улица и
список домов через запятую. Длинные списки домов в json удобнее,
поэтому там дома пишутся отдельными объектами.
"""
import csv
import json
from collections.abc import Iterable
from pathlib import Path

from app.parser.companies import CompanyDirectory

CSV_FIELDS = ("name", "email", "phone", "website", "city", "street", "houses")


def write_csv(directory: dict[str, CompanyDirectory], destination: Path) -> int:
    """Пишет справочник в csv, возвращает число строк."""
    rows = 0
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in _rows(directory):
            writer.writerow(row)
            rows += 1
    return rows


def write_json(directory: dict[str, CompanyDirectory], destination: Path) -> int:
    """Пишет справочник в json, возвращает число компаний."""
    companies = []
    for company in _ordered(directory):
        companies.append(
            {
                "ogrn": company.ogrn,
                "name": company.name,
                "email": company.email,
                "phone": company.phone,
                "website": company.website,
                "city": company.city,
                "houses": [
                    {
                        "street": street,
                        "number": number,
                        "corpus": corpus,
                    }
                    for street, items in _ordered_streets(company)
                    for number, corpus in items
                ],
            }
        )
    destination.write_text(
        json.dumps(companies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(companies)


def _rows(directory: dict[str, CompanyDirectory]) -> Iterable[dict[str, object]]:
    """Строки csv: по одной на пару «компания — улица»."""
    for company in _ordered(directory):
        for street, items in _ordered_streets(company):
            yield {
                "name": company.name,
                "email": company.email,
                "phone": company.phone,
                "website": company.website,
                "city": company.city,
                "street": street,
                "houses": ",".join(_house_fragment(number, corpus) for number, corpus in items),
            }


def _ordered(directory: dict[str, CompanyDirectory]) -> list[CompanyDirectory]:
    return sorted(directory.values(), key=lambda company: (company.city, company.name))


def _ordered_streets(company: CompanyDirectory) -> list[tuple[str, list[tuple[int, str | None]]]]:
    return [
        (street, sorted(items, key=lambda house: (house[0], house[1] or "")))
        for street, items in sorted(company.streets.items())
    ]


def _house_fragment(number: int, corpus: str | None) -> str:
    return f"{number}{corpus or ''}"
