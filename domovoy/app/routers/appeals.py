"""Обращения жильцов и отправка их в управляющие компании."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Address, Appeal, AppealStatus, User
from app.schemas import AppealIn, AppealOut, AppealStatusIn
from app.services.addresses import normalize_house, normalize_street
from app.services.mailer import build_message, send_email
from app.services.matching import find_company

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/appeals", tags=["appeals"])
UPLOAD_DIR = Path("uploads")
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if x_admin_token != settings.admin_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен admin-токен")


def deliver_appeal(appeal_id: int) -> None:
    """Фоновая отправка письма в УК. Работает в своей сессии БД."""
    db = SessionLocal()
    try:
        appeal = db.get(Appeal, appeal_id)
        if not appeal or not appeal.company:
            logger.warning("Обращение %s без УК, письмо не отправлено", appeal_id)
            if appeal:
                appeal.status = AppealStatus.FAILED
                appeal.error = "Управляющая компания для адреса не найдена"
                db.commit()
            return

        email = build_message(
            number=appeal.number,
            to_email=appeal.company.email,
            address=appeal.address_text,
            category=appeal.category,
            contact=appeal.contact,
            text=appeal.message,
            created_at=appeal.created_at,
            photo_path=appeal.photo_path,
        )
        try:
            send_email(email)
        except Exception as error:  # noqa: BLE001 — показываем причину жильцу и админу
            logger.exception("Не удалось отправить обращение %s", appeal.number)
            appeal.status = AppealStatus.FAILED
            appeal.error = str(error)
        else:
            appeal.status = AppealStatus.SENT
            appeal.sent_at = datetime.now(timezone.utc)
            appeal.error = None
        db.commit()
    finally:
        db.close()


@router.post("/photo", status_code=status.HTTP_201_CREATED)
async def upload_photo(file: UploadFile = File(...)) -> dict[str, str]:
    """Загрузка фото к обращению. Возвращает путь для поля photo_path."""
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Нужен файл изображения")

    payload = await file.read()
    if len(payload) > MAX_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 10 МБ")

    UPLOAD_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(payload)
    return {"photo_path": str(path)}


@router.post("", response_model=AppealOut, status_code=status.HTTP_201_CREATED)
def create_appeal(
    payload: AppealIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Appeal:
    """Создаёт обращение и ставит письмо в очередь на отправку."""
    user: User | None = None
    if payload.user_id:
        user = db.get(User, payload.user_id)
    elif payload.max_user_id:
        user = db.execute(
            select(User).where(User.max_user_id == payload.max_user_id)
        ).scalar_one_or_none()

    city, street, house, flat = payload.city, payload.street, payload.house, payload.flat
    if not (street and house) and user and user.addresses:
        primary: Address = user.addresses[0]
        city, street, house, flat = primary.city, primary.street, primary.house, primary.flat

    if not (street and house):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Нужен адрес: улица и дом")

    address_text = ", ".join(part for part in [city, f"{street}, д. {house}"] if part)
    if flat:
        address_text += f", кв. {flat}"

    company = find_company(db, normalize_street(street), normalize_house(house))

    appeal = Appeal(
        user_id=user.id if user else None,
        company_id=company.id if company else None,
        category=payload.category,
        message=payload.message,
        address_text=address_text,
        contact=payload.contact or (user.phone or user.email if user else None),
        photo_path=payload.photo_path,
        status=AppealStatus.NEW,
        source=payload.source,
    )
    db.add(appeal)
    db.commit()
    db.refresh(appeal)

    if company:
        background.add_task(deliver_appeal, appeal.id)
    else:
        appeal.status = AppealStatus.FAILED
        appeal.error = "Управляющая компания для адреса не найдена"
        db.commit()
        db.refresh(appeal)

    return appeal


@router.get("", response_model=list[AppealOut], dependencies=[Depends(require_admin)])
def list_appeals(
    db: Session = Depends(get_db),
    status_filter: AppealStatus | None = None,
    limit: int = 200,
) -> list[Appeal]:
    """Список обращений для панели УК. Требует admin-токен."""
    statement = select(Appeal).order_by(Appeal.created_at.desc()).limit(limit)
    if status_filter:
        statement = statement.where(Appeal.status == status_filter)
    return list(db.execute(statement).scalars().all())


@router.get("/mine", response_model=list[AppealOut])
def my_appeals(
    user_id: int | None = None,
    max_user_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[Appeal]:
    """Обращения одного жильца. Раздел «Мои обращения» в боте."""
    if not user_id and not max_user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен user_id или max_user_id")
    if not user_id:
        user = db.execute(select(User).where(User.max_user_id == max_user_id)).scalar_one_or_none()
        if not user:
            return []
        user_id = user.id
    statement = select(Appeal).where(Appeal.user_id == user_id).order_by(Appeal.created_at.desc())
    return list(db.execute(statement).scalars().all())


@router.get("/{appeal_id}", response_model=AppealOut)
def read_appeal(appeal_id: int, db: Session = Depends(get_db)) -> Appeal:
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    return appeal


@router.patch(
    "/{appeal_id}/status", response_model=AppealOut, dependencies=[Depends(require_admin)]
)
def update_status(appeal_id: int, payload: AppealStatusIn, db: Session = Depends(get_db)) -> Appeal:
    """Смена статуса из панели УК."""
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    appeal.status = payload.status
    db.commit()
    db.refresh(appeal)
    return appeal


@router.post("/{appeal_id}/retry", response_model=AppealOut, dependencies=[Depends(require_admin)])
def retry_appeal(
    appeal_id: int, background: BackgroundTasks, db: Session = Depends(get_db)
) -> Appeal:
    """Повторная попытка отправки письма."""
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    if not appeal.company_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "У обращения нет управляющей компании")
    background.add_task(deliver_appeal, appeal.id)
    return appeal
