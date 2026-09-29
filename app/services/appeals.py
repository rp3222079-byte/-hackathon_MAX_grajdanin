"""Создание обращения: номер для жильца и поиск УК по дому.

Само письмо в УК отправляет app/services/mailer.py, здесь только запись
в базе: номер, адрес и получатель.
"""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import APPEAL_STATUS_NEW, Address, Appeal, ManagementCompany
from app.services.directory import find_company

APPEAL_NUMBER_FORMAT = "DM-{:05d}"
# Два обращения в одну секунду могут получить один номер: тогда пробуем снова
NUMBER_ATTEMPTS = 3


def next_appeal_number(db: Session) -> str:
    """Следующий номер обращения: DM-00001, DM-00002 и так далее."""
    last = db.scalar(select(func.max(Appeal.number)))
    if not last:
        return APPEAL_NUMBER_FORMAT.format(1)
    return APPEAL_NUMBER_FORMAT.format(int(last.rsplit("-", 1)[-1]) + 1)


def format_address_text(address: Address) -> str:
    """Адрес строкой для обращения: «Новосибирск, ул. Ленина, 11к2, кв. 5»."""
    house = f"{address.house_number}{address.house_corpus or ''}"
    parts = [address.city, address.street, house]
    if address.flat:
        parts.append(f"кв. {address.flat}")
    return ", ".join(parts)


def find_company_for_address(db: Session, address: Address) -> ManagementCompany | None:
    """УК, которой закреплён дом жильца; None — если дома в справочнике нет."""
    return find_company(
        db, address.city, address.street, address.house_number, address.house_corpus
    )


def create_appeal(
    db: Session,
    *,
    user_id: int | None = None,
    address: Address | None = None,
    address_text: str | None = None,
    subject: str,
    text: str,
    photo_path: str | None = None,
    contact: str | None = None,
) -> Appeal:
    """Сохраняет обращение и подставляет номер и УК.

    Адрес обязателен хотя бы в одном виде: заведённым адресом жильца
    или текстом.
    """
    if address is None and not address_text:
        raise ValueError("нужен адрес жильца или его текст")

    if address is not None and not address_text:
        address_text = format_address_text(address)
    company = find_company_for_address(db, address) if address is not None else None

    for attempt in range(1, NUMBER_ATTEMPTS + 1):
        appeal = Appeal(
            number=next_appeal_number(db),
            user_id=user_id,
            address_id=address.id if address else None,
            company_id=company.id if company else None,
            address_text=address_text,
            subject=subject,
            text=text,
            photo_path=photo_path,
            contact=contact,
            status=APPEAL_STATUS_NEW,
        )
        db.add(appeal)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == NUMBER_ATTEMPTS:
                raise
            continue
        db.refresh(appeal)
        return appeal
    raise RuntimeError("недостижимо")
