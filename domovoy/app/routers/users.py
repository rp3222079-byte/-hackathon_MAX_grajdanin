"""Пользователи и их адреса."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Address, User
from app.schemas import AddressIn, AddressOut, UserOut, UserSettings, UserUpsert
from app.services.addresses import normalize_house, normalize_street

router = APIRouter(prefix="/api/users", tags=["users"])


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return user


@router.post("", response_model=UserOut, status_code=status.HTTP_200_OK)
def upsert_user(payload: UserUpsert, db: Session = Depends(get_db)) -> User:
    """Создаёт пользователя или возвращает существующего по max_user_id."""
    user: User | None = None
    if payload.max_user_id:
        user = db.execute(
            select(User).where(User.max_user_id == payload.max_user_id)
        ).scalar_one_or_none()

    if user is None:
        user = User(max_user_id=payload.max_user_id)
        db.add(user)

    if payload.full_name:
        user.full_name = payload.full_name
    if payload.phone:
        user.phone = payload.phone
    if payload.email:
        user.email = str(payload.email)

    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
def read_user(user_id: int, db: Session = Depends(get_db)) -> User:
    return get_user_or_404(db, user_id)


@router.patch("/{user_id}/settings", response_model=UserOut)
def update_settings(user_id: int, payload: UserSettings, db: Session = Depends(get_db)) -> User:
    user = get_user_or_404(db, user_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}/addresses", response_model=list[AddressOut])
def list_addresses(user_id: int, db: Session = Depends(get_db)) -> list[Address]:
    return get_user_or_404(db, user_id).addresses


@router.post("/{user_id}/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
def add_address(user_id: int, payload: AddressIn, db: Session = Depends(get_db)) -> Address:
    user = get_user_or_404(db, user_id)
    street_key = normalize_street(payload.street)
    house_key = normalize_house(payload.house)
    if not street_key or not house_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Не удалось разобрать адрес")

    duplicate = any(
        address.street_key == street_key and address.house_key == house_key
        for address in user.addresses
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой адрес уже добавлен")

    address = Address(
        user_id=user.id,
        city=payload.city,
        street=payload.street,
        house=payload.house,
        flat=payload.flat,
        street_key=street_key,
        house_key=house_key,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/{user_id}/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(user_id: int, address_id: int, db: Session = Depends(get_db)) -> None:
    address = db.get(Address, address_id)
    if not address or address.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Адрес не найден")
    db.delete(address)
    db.commit()
