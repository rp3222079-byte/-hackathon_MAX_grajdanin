"""Отключения: список и фильтр по адресу.

Фильтр по дому идёт через parse_house_list, потому что список домов
хранится строкой источника: «1-15, 12к2».
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import Outage
from app.schemas import OutageOut, UtilityName
from app.services.addresses import normalize_street, parse_house_list

router = APIRouter(prefix="/outages", tags=["отключения"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


@router.get("", response_model=list[OutageOut], summary="Список отключений")
def list_outages(
    city: str | None = Query(default=None, description="Город, например «Новосибирск»."),
    street: str | None = Query(default=None, description="Улица как у жильца: «ул. Ленина» или «Ленина»."),
    house_number: int | None = Query(default=None, ge=1, description="Номер дома."),
    house_corpus: str | None = Query(default=None, description="Корпус: «к2»."),
    utility: UtilityName | None = Query(default=None, description="Ресурс: water или electricity."),
    starts_after: datetime | None = Query(default=None, description="Отключения, которые начались не раньше."),
    starts_before: datetime | None = Query(default=None, description="Отключения, которые начались не позже."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Outage]:
    """Отдаёт отключения, новые сверху.

    С городом, ресурсом и датами фильтр делает база, а с улицей и домом —
    Python: список домов лежит в строке и разбирается на ходу.
    """
    query = select(Outage)
    if city:
        query = query.where(func.lower(Outage.city) == city.strip().lower())
    if utility:
        query = query.where(Outage.utility == utility)
    if starts_after:
        query = query.where(Outage.starts_at >= starts_after)
    if starts_before:
        query = query.where(Outage.starts_at <= starts_before)
    query = query.order_by(Outage.starts_at.desc(), Outage.id.desc())

    if street or house_number is not None:
        rows = db.scalars(query).all()
        found = [row for row in rows if hits_house(row, street, house_number, house_corpus)]
        return found[offset : offset + limit]

    return list(db.scalars(query.offset(offset).limit(limit)))


@router.get("/{outage_id}", response_model=OutageOut, summary="Одно отключение")
def get_outage(outage_id: int, db: Session = Depends(get_db)) -> Outage:
    """Отдаёт отключение по id."""
    outage = db.get(Outage, outage_id)
    if outage is None:
        raise NotFoundError(f"Отключение {outage_id} не найдено")
    return outage


def hits_house(outage: Outage, street: str | None, house_number: int | None, house_corpus: str | None) -> bool:
    """Задевает ли отключение этот дом: улица совпала и дом есть в списке."""
    if street and normalize_street(street) != normalize_street(outage.street):
        return False
    if house_number is None:
        return True
    try:
        houses = parse_house_list(outage.houses_raw)
    except ValueError:
        # кривой список домов в источнике не должен ронять весь ответ
        return False
    return (house_number, house_corpus) in houses
