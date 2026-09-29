"""Отключения: список, фильтр по адресу и уведомления жильцам.

Фильтр по дому идёт через parse_house_list, потому что список домов
хранится строкой источника: «1-15, 12к2». Город и улица сравниваются
на Python: lower() в SQLite не понимает кириллицу.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import Outage
from app.routers.common import require_user
from app.schemas import OutageNotificationOut, OutageNotified, OutageOut, UtilityName
from app.services.matching import outage_covers
from app.services.notifications import (
    address_line,
    mark_outage_notified,
    pending_outage_notifications,
)

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
    ends_after: datetime | None = Query(
        default=None, description="Только те, что ещё не закончились к этому моменту."
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Outage]:
    """Отдаёт отключения, новые сверху.

    Ресурс и даты отсекает база, а город, улицу и дом — Python:
    список домов лежит в строке и разбирается на ходу.
    """
    query = select(Outage)
    if utility:
        query = query.where(Outage.utility == utility)
    if starts_after:
        query = query.where(Outage.starts_at >= starts_after)
    if starts_before:
        query = query.where(Outage.starts_at <= starts_before)
    if ends_after:
        query = query.where(or_(Outage.ends_at.is_(None), Outage.ends_at > ends_after))
    query = query.order_by(Outage.starts_at.desc(), Outage.id.desc())

    if city or street or house_number is not None:
        rows = db.scalars(query).all()
        found = [row for row in rows if matches_place(row, city, street, house_number, house_corpus)]
        return found[offset : offset + limit]

    return list(db.scalars(query.offset(offset).limit(limit)))


@router.get(
    "/notifications/pending",
    response_model=list[OutageNotificationOut],
    summary="Кого пора предупредить об отключении",
)
def list_pending_notifications(db: Session = Depends(get_db)) -> list[OutageNotificationOut]:
    """Отключения, о которых жильцы ещё не знают, с учётом их настроек.

    Бот раз в минуту забирает этот список, отправляет сообщения и отмечает
    каждое через POST /outages/{id}/notified.
    """
    return [
        OutageNotificationOut(
            user_id=item.user.id,
            max_user_id=item.user.max_user_id,
            address=address_line(item.address),
            outage=OutageOut.model_validate(item.outage),
        )
        for item in pending_outage_notifications(db)
    ]


@router.post(
    "/{outage_id}/notified",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отметить, что жилец уведомлён",
)
def mark_notified(outage_id: int, payload: OutageNotified, db: Session = Depends(get_db)) -> Response:
    """Больше не присылать жильцу это отключение."""
    get_outage(outage_id, db)
    require_user(db, payload.user_id)
    mark_outage_notified(db, payload.user_id, outage_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{outage_id}", response_model=OutageOut, summary="Одно отключение")
def get_outage(outage_id: int, db: Session = Depends(get_db)) -> Outage:
    """Отдаёт отключение по id."""
    outage = db.get(Outage, outage_id)
    if outage is None:
        raise NotFoundError(f"Отключение {outage_id} не найдено")
    return outage


def matches_place(
    outage: Outage,
    city: str | None,
    street: str | None,
    house_number: int | None,
    house_corpus: str | None,
) -> bool:
    """Задевает ли отключение этот адрес: город, улица совпали и дом есть в списке."""
    return outage_covers(
        outage.city,
        outage.street,
        outage.houses_raw,
        city=city,
        street=street,
        house_number=house_number,
        house_corpus=house_corpus,
    )
