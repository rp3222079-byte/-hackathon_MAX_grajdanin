"""Создание отключений: разбор адресов и защита от дублей."""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Outage, OutageArea, UtilityType
from app.services.addresses import parse_address_block


def make_fingerprint(utility: UtilityType, raw_addresses: str, starts_at: datetime) -> str:
    """Отпечаток отключения: один и тот же текст от источника не заведёт дубль."""
    payload = f"{utility.value}|{' '.join(raw_addresses.split()).lower()}|{starts_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def create_outage(
    db: Session,
    *,
    utility: UtilityType,
    raw_addresses: str,
    starts_at: datetime,
    ends_at: datetime | None = None,
    reason: str | None = None,
    is_planned: bool = True,
    source: str = "manual",
    city: str | None = None,
) -> tuple[Outage, bool]:
    """Создаёт отключение. Возвращает (отключение, создано_ли_оно_сейчас)."""
    fingerprint = make_fingerprint(utility, raw_addresses, starts_at)
    existing = db.execute(select(Outage).where(Outage.fingerprint == fingerprint)).scalar_one_or_none()
    if existing:
        return existing, False

    outage = Outage(
        utility=utility,
        city=city or settings.default_city,
        raw_addresses=raw_addresses,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason,
        is_planned=is_planned,
        source=source,
        fingerprint=fingerprint,
    )
    db.add(outage)
    db.flush()

    for street_key, house_key in parse_address_block(raw_addresses):
        db.add(OutageArea(outage_id=outage.id, street_key=street_key, house_key=house_key))

    db.commit()
    db.refresh(outage)
    return outage, True
