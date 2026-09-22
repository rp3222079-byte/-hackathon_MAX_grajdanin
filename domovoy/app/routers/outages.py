"""Отключения: список, фильтры, ручное создание."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Address, Outage, OutageArea, User, UtilityType
from app.schemas import OutageIn, OutageOut
from app.services.addresses import normalize_house, normalize_street
from app.services.matching import outages_for_address
from app.services.outages import create_outage

router = APIRouter(prefix="/api/outages", tags=["outages"])


@router.get("", response_model=list[OutageOut])
def list_outages(
    db: Session = Depends(get_db),
    utility: UtilityType | None = None,
    street: str | None = None,
    house: str | None = None,
    active_only: bool = Query(default=True, description="Только текущие и будущие"),
    days_ahead: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Outage]:
    """Список отключений с фильтрами. Используется сайтом и ботом."""
    now = datetime.now(timezone.utc)
    statement = select(Outage).order_by(Outage.starts_at)

    if utility:
        statement = statement.where(Outage.utility == utility)
    if active_only:
        statement = statement.where(Outage.starts_at <= now + timedelta(days=days_ahead))
    if street:
        street_key = normalize_street(street)
        statement = statement.join(OutageArea, OutageArea.outage_id == Outage.id).where(
            OutageArea.street_key == street_key
        )
        if house:
            statement = statement.where(OutageArea.house_key == normalize_house(house))

    outages = list(db.execute(statement.limit(limit)).scalars().unique().all())
    if not active_only:
        return outages
    return [outage for outage in outages if outage.ends_at is None or _aware(outage.ends_at) >= now]


@router.get("/for-user/{user_id}", response_model=list[OutageOut])
def outages_for_user(user_id: int, db: Session = Depends(get_db)) -> list[Outage]:
    """Актуальные отключения по всем адресам пользователя."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    seen: set[int] = set()
    result: list[Outage] = []
    for address in user.addresses:
        for outage in outages_for_address(db, address):
            if outage.id not in seen:
                seen.add(outage.id)
                result.append(outage)
    return sorted(result, key=lambda item: _aware(item.starts_at))


@router.post("", response_model=OutageOut, status_code=status.HTTP_201_CREATED)
def add_outage(payload: OutageIn, db: Session = Depends(get_db)) -> Outage:
    """Ручное создание отключения: для демо и для админа."""
    outage, created = create_outage(
        db,
        utility=payload.utility,
        raw_addresses=payload.raw_addresses,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
        is_planned=payload.is_planned,
        source=payload.source,
        city=payload.city,
    )
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такое отключение уже есть")
    return outage


@router.get("/check", response_model=list[OutageOut])
def check_address(
    street: str,
    house: str,
    db: Session = Depends(get_db),
) -> list[Outage]:
    """Проверка адреса без регистрации — для главной страницы сайта."""
    probe = Address(
        city="",
        street=street,
        house=house,
        street_key=normalize_street(street),
        house_key=normalize_house(house),
        user_id=0,
    )
    if not probe.street_key or not probe.house_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Не удалось разобрать адрес")
    return outages_for_address(db, probe)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
