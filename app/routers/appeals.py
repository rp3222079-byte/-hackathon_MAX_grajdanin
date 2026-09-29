"""Обращения жильцов: создать, посмотреть, сменить статус.

Письмо в УК отправляет бот (app/services/mailer.py) и сам ставит статус
sent или failed. Статусы in_progress и resolved ставит УК на странице
обращения по ссылке из письма (app/routers/uk.py).
"""
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import Appeal
from app.routers.common import require_address, require_user
from app.schemas import (
    AppealCreate,
    AppealNotified,
    AppealOut,
    AppealStatus,
    AppealStatusUpdate,
    AppealUpdateOut,
)
from app.services.appeals import create_appeal
from app.services.notifications import pending_appeal_updates
from app.services.statuses import change_status

router = APIRouter(prefix="/appeals", tags=["обращения"])


@router.post("", response_model=AppealOut, status_code=status.HTTP_201_CREATED, summary="Создать обращение")
def post_appeal(payload: AppealCreate, db: Session = Depends(get_db)) -> Appeal:
    """Принимает обращение жильца.

    Возвращает номер обращения и ссылку для УК. Если адрес заведён
    в профиле, УК ищется по дому и письмо уходит именно ей.
    """
    user = require_user(db, payload.user_id) if payload.user_id else None
    address = require_address(db, payload.address_id) if payload.address_id else None
    if address is not None and user is not None and address.user_id != user.id:
        raise NotFoundError(f"Адрес {address.id} не принадлежит жильцу {user.id}")

    return create_appeal(
        db,
        user_id=user.id if user else None,
        address=address,
        address_text=payload.address_text,
        subject=payload.subject,
        text=payload.text,
        photo_path=payload.photo_path,
        contact=payload.contact,
    )


@router.get("", response_model=list[AppealOut], summary="Список обращений")
def list_appeals(
    user_id: int | None = Query(default=None, ge=1, description="Обращения одного жильца."),
    company_id: int | None = Query(default=None, ge=1, description="Обращения одной УК."),
    status_filter: AppealStatus | None = Query(default=None, alias="status", description="Статус обращения."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Appeal]:
    """Отдаёт обращения, новые сверху."""
    query = select(Appeal)
    if user_id:
        query = query.where(Appeal.user_id == user_id)
    if company_id:
        query = query.where(Appeal.company_id == company_id)
    if status_filter:
        query = query.where(Appeal.status == status_filter)
    return list(db.scalars(query.order_by(Appeal.id.desc()).offset(offset).limit(limit)))


@router.get(
    "/updates/pending",
    response_model=list[AppealUpdateOut],
    summary="Новые статусы, о которых жилец не знает",
)
def list_pending_updates(db: Session = Depends(get_db)) -> list[AppealUpdateOut]:
    """Обращения, которые УК перевела в работу или решила.

    Бот забирает список, пишет жильцу и отмечает через
    POST /appeals/{number}/notified — отметка хранится в базе,
    поэтому перезапуск бота ничего не теряет и не дублирует.
    """
    return [
        AppealUpdateOut(
            number=appeal.number,
            status=appeal.status,
            subject=appeal.subject,
            uk_comment=appeal.uk_comment,
            max_user_id=appeal.user.max_user_id,
            company_name=appeal.company.name if appeal.company else None,
        )
        for appeal in pending_appeal_updates(db)
    ]


@router.post(
    "/{number}/notified",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отметить, что жилец узнал о статусе",
)
def mark_notified(number: str, payload: AppealNotified, db: Session = Depends(get_db)) -> Response:
    appeal = _require_appeal(db, number)
    appeal.notified_status = payload.status
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{number}", response_model=AppealOut, summary="Изменить статус обращения")
def patch_appeal_status(number: str, payload: AppealStatusUpdate, db: Session = Depends(get_db)) -> Appeal:
    """Меняет статус: sent/failed ставит бот после отправки письма,
    in_progress/resolved — управляющая компания."""
    return change_status(db, _require_appeal(db, number), payload.status, payload.comment)


@router.get("/{number}", response_model=AppealOut, summary="Обращение по номеру")
def get_appeal(number: str, db: Session = Depends(get_db)) -> Appeal:
    """Отдаёт обращение по номеру вида DM-00001."""
    return _require_appeal(db, number)


def _require_appeal(db: Session, number: str) -> Appeal:
    appeal = db.scalar(select(Appeal).where(Appeal.number == number))
    if appeal is None:
        raise NotFoundError(f"Обращение {number} не найдено")
    return appeal
