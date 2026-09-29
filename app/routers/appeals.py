from datetime import datetime
"""Обращения жильцов: создать и посмотреть.

Письмо в УК отправляется отдельно (app/services/mailer.py), поэтому
статус обращения здесь только «new».
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import Appeal
from app.routers.common import require_address, require_user
from app.schemas import AppealCreate, AppealOut, AppealStatus, AppealStatusUpdate
from app.services.appeals import create_appeal

router = APIRouter(prefix="/appeals", tags=["обращения"])


@router.post("", response_model=AppealOut, status_code=status.HTTP_201_CREATED, summary="Создать обращение")
def post_appeal(payload: AppealCreate, db: Session = Depends(get_db)) -> Appeal:
    """Принимает обращение жильца.

    Возвращает номер обращения: по нему жилец спросит о судьбе письма,
    а панель УК — о статусе. Если адрес заведён в профиле, УК ищется
    по дому и письмо уходит именно ей.
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
    """Отдаёт обращения, новые сверху — так их видит панель УК."""
    query = select(Appeal)
    if user_id:
        query = query.where(Appeal.user_id == user_id)
    if company_id:
        query = query.where(Appeal.company_id == company_id)
    if status_filter:
        query = query.where(Appeal.status == status_filter)
    return list(db.scalars(query.order_by(Appeal.id.desc()).offset(offset).limit(limit)))


@router.patch("/{number}", response_model=AppealOut, summary="Изменить статус обращения")
def patch_appeal_status(number: str, payload: AppealStatusUpdate, db: Session = Depends(get_db)) -> Appeal:
    """Меняет статус: sent/failed ставит бот сразу после отправки письма,
    in_progress/resolved — управляющая компания по ответу на письмо."""
    appeal = db.scalar(select(Appeal).where(Appeal.number == number))
    if appeal is None:
        raise NotFoundError(f"Обращение {number} не найдено")

    appeal.status = payload.status
    if payload.status == "sent" and appeal.sent_at is None:
        appeal.sent_at = datetime.now()
    if payload.status == "resolved" and appeal.resolved_at is None:
        appeal.resolved_at = datetime.now()
    db.commit()
    db.refresh(appeal)
    return appeal


@router.get("/{number}", response_model=AppealOut, summary="Обращение по номеру")
def get_appeal(number: str, db: Session = Depends(get_db)) -> Appeal:
    """Отдаёт обращение по номеру вида DM-00001."""
    appeal = db.scalar(select(Appeal).where(Appeal.number == number))
    if appeal is None:
        raise NotFoundError(f"Обращение {number} не найдено")
    return appeal
