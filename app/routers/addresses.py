"""Адреса жильца: добавление, список, удаление.

Отключения по адресу бот и сайт смотрят через GET /outages, а не здесь.
"""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ConflictError
from app.models import Address
from app.routers.common import find_address, require_address, require_user
from app.schemas import AddressCreate, AddressOut

router = APIRouter(tags=["адреса"])


@router.post(
    "/users/{user_id}/addresses",
    response_model=AddressOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить адрес",
)
def create_address(user_id: int, payload: AddressCreate, db: Session = Depends(get_db)) -> Address:
    """Добавляет адрес жильцу.

    Первый адрес становится основным, а тот же дом дважды не добавляется.
    """
    user = require_user(db, user_id)
    duplicate = find_address(
        db,
        user.id,
        payload.city,
        payload.street,
        payload.house_number,
        payload.house_corpus,
    )
    if duplicate is not None:
        raise ConflictError("Этот адрес уже добавлен")

    has_addresses = db.scalar(select(Address.id).where(Address.user_id == user.id).limit(1)) is not None
    address = Address(
        user_id=user.id,
        city=payload.city,
        street=payload.street,
        house_number=payload.house_number,
        house_corpus=payload.house_corpus,
        flat=payload.flat,
        is_primary=payload.is_primary or not has_addresses,
    )
    if address.is_primary:
        _drop_other_primary(db, user.id, None)
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.get("/users/{user_id}/addresses", response_model=list[AddressOut], summary="Адреса жильца")
def list_addresses(user_id: int, db: Session = Depends(get_db)) -> list[Address]:
    """Отдаёт все адреса жильца, основной — первым."""
    require_user(db, user_id)
    return list(
        db.scalars(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_primary.desc(), Address.id)
        )
    )


@router.get("/addresses/{address_id}", response_model=AddressOut, summary="Один адрес")
def get_address(address_id: int, db: Session = Depends(get_db)) -> Address:
    """Отдаёт адрес по id."""
    return require_address(db, address_id)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить адрес")
def delete_address(address_id: int, db: Session = Depends(get_db)) -> Response:
    """Удаляет адрес жильца."""
    db.delete(require_address(db, address_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _drop_other_primary(db: Session, user_id: int, keep_address_id: int | None) -> None:
    """Снимает отметку основного с остальных адресов жильца."""
    query = select(Address).where(Address.user_id == user_id, Address.is_primary.is_(True))
    if keep_address_id is not None:
        query = query.where(Address.id != keep_address_id)
    for address in db.scalars(query):
        address.is_primary = False
