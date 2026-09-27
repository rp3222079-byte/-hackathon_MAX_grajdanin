"""Создание обращения: номер для жильца и поиск УК по дому.

Само письмо в УК отправляет app/services/mailer.py, здесь только запись
в базе: номер, адрес и получатель.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    APPEAL_STATUS_NEW,
    Address,
    Appeal,
    CompanyHouse,
    ManagementCompany,
)
from app.services.addresses import normalize_street

APPEAL_NUMBER_FORMAT = "DM-{:05d}"


def next_appeal_number(db: Session) -> str:
    """Следующий номер обращения: DM-00001, DM-00002 и так далее."""
    last = db.scalar(select(func.max(Appeal.number)))
    if not last:
        return APPEAL_NUMBER_FORMAT.format(1)
    return APPEAL_NUMBER_FORMAT.format(int(last.rsplit("-", 1)[-1]) + 1)


def format_address_text(address: Address) -> str:
    """Адрес строкой для обращения: «Новосибирск, ул. Ленина, 11 к2, кв. 5»."""
    house = f"{address.house_number}{address.house_corpus or ''}"
    parts = [address.city, address.street, house]
    if address.flat:
        parts.append(f"кв. {address.flat}")
    return ", ".join(parts)


def find_company_for_address(db: Session, address: Address) -> ManagementCompany | None:
    """УК, которой закреплён дом жильца; None — если дома в справочнике нет.

    Улица сравнивается через normalize_street: жилец пишет «ул. Ленина»,
    а в справочнике «улица Ленина» — это один и тот же дом.
    """
    houses = db.scalars(
        select(CompanyHouse).where(CompanyHouse.house_number == address.house_number)
    ).all()
    city = address.city.strip().lower()
    street = normalize_street(address.street)
    for house in houses:
        if house.city.strip().lower() != city or normalize_street(house.street) != street:
            continue
        if address.house_corpus and house.house_corpus != address.house_corpus:
            continue
        return db.get(ManagementCompany, house.company_id)
    return None


def create_appeal(
    db: Session,
    *,
    user_id: int | None = None,
    address: Address | None = None,
    address_text: str | None = None,
    subject: str,
    text: str,
    photo_path: str | None = None,
) -> Appeal:
    """Сохраняет обращение и подставляет номер и УК.

    Адрес обязателен хотя бы в одном виде: заведённым адресом жильца
    или текстом.
    """
    if address is None and not address_text:
        raise ValueError("нужен адрес жильца или его текст")

    if address is not None and not address_text:
        address_text = format_address_text(address)

    appeal = Appeal(
        number=next_appeal_number(db),
        user_id=user_id,
        address_id=address.id if address else None,
        address_text=address_text,
        subject=subject,
        text=text,
        photo_path=photo_path,
        status=APPEAL_STATUS_NEW,
    )
    if address is not None:
        company = find_company_for_address(db, address)
        if company is not None:
            appeal.company_id = company.id
    db.add(appeal)
    db.commit()
    db.refresh(appeal)
    return appeal
