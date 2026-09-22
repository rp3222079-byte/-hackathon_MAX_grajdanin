"""Сопоставление отключений с жителями и поиск управляющей компании."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Address,
    ManagementCompany,
    Notification,
    Outage,
    OutageArea,
    ServedHouse,
    User,
    UtilityType,
)

WATER_TYPES = {UtilityType.WATER_COLD, UtilityType.WATER_HOT}


def users_for_outage(db: Session, outage: Outage) -> list[tuple[User, Address]]:
    """Кого затрагивает отключение, с учётом настроек уведомлений."""
    area_keys = {(area.street_key, area.house_key) for area in outage.areas}
    if not area_keys:
        return []

    streets = {street for street, _ in area_keys}
    statement = (
        select(User, Address)
        .join(Address, Address.user_id == User.id)
        .where(User.is_active.is_(True), Address.street_key.in_(streets))
    )

    result: list[tuple[User, Address]] = []
    for user, address in db.execute(statement).all():
        if (address.street_key, address.house_key) not in area_keys:
            continue
        if outage.utility in WATER_TYPES and not user.notify_water:
            continue
        if outage.utility is UtilityType.ELECTRICITY and not user.notify_electricity:
            continue
        result.append((user, address))
    return result


def already_notified(db: Session, user_id: int, outage_id: int) -> bool:
    statement = select(Notification).where(
        Notification.user_id == user_id, Notification.outage_id == outage_id
    )
    return db.execute(statement).scalar_one_or_none() is not None


def find_company(db: Session, street_key: str, house_key: str) -> ManagementCompany | None:
    """Ищет УК по дому, затем по улице — на случай неполного справочника."""
    statement = (
        select(ManagementCompany)
        .join(ServedHouse, ServedHouse.company_id == ManagementCompany.id)
        .where(ServedHouse.street_key == street_key, ServedHouse.house_key == house_key)
    )
    company = db.execute(statement).scalars().first()
    if company:
        return company

    fallback = (
        select(ManagementCompany)
        .join(ServedHouse, ServedHouse.company_id == ManagementCompany.id)
        .where(ServedHouse.street_key == street_key)
    )
    return db.execute(fallback).scalars().first()


def outages_for_address(db: Session, address: Address, only_active: bool = True) -> list[Outage]:
    """Отключения, которые касаются конкретного адреса."""
    from datetime import datetime, timezone

    statement = (
        select(Outage)
        .join(OutageArea, OutageArea.outage_id == Outage.id)
        .where(OutageArea.street_key == address.street_key, OutageArea.house_key == address.house_key)
        .order_by(Outage.starts_at)
    )
    outages = list(db.execute(statement).scalars().unique().all())
    if not only_active:
        return outages

    now = datetime.now(timezone.utc)
    return [outage for outage in outages if outage.ends_at is None or _aware(outage.ends_at) >= now]


def _aware(value):
    from datetime import timezone

    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
