"""Пользователи: регистрация жильца и настройки уведомлений."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routers.common import require_user
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["пользователи"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Регистрация жильца")
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    """Создаёт жильца.

    Повторный запрос с тем же max_user_id возвращает уже созданного жильца:
    бот здоровается при каждом запуске, дублей быть не должно.
    """
    if payload.max_user_id:
        existing = db.scalar(select(User).where(User.max_user_id == payload.max_user_id))
        if existing is not None:
            return existing

    user = User(max_user_id=payload.max_user_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut, summary="Жилец с его адресами")
def get_user(user_id: int, db: Session = Depends(get_db)) -> User:
    """Отдаёт жильца и его адреса."""
    return require_user(db, user_id)


@router.patch("/{user_id}", response_model=UserOut, summary="Настройки уведомлений")
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)) -> User:
    """Включает и выключает уведомления: общий выключатель и ресурсы по отдельности."""
    user = require_user(db, user_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
