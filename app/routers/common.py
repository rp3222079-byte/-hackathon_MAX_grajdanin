"""Общие помощники роутеров: достать запись или сообщить, что её нет."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Address, User


def require_user(db: Session, user_id: int) -> User:
    """Жилец по id или NotFoundError."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"Жилец {user_id} не найден")
    return user


def require_address(db: Session, address_id: int) -> Address:
    """Адрес по id или NotFoundError."""
    address = db.get(Address, address_id)
    if address is None:
        raise NotFoundError(f"Адрес {address_id} не найден")
    return address


def find_address(db: Session, user_id: int, city: str, street: str, house_number: int, house_corpus: str | None) -> Address | None:
    """Адрес жильца по его полям — чтобы не заводить один дом дважды."""
    query = select(Address).where(
        Address.user_id == user_id,
        Address.city == city,
        Address.street == street,
        Address.house_number == house_number,
    )
    if house_corpus is None:
        query = query.where(Address.house_corpus.is_(None))
    else:
        query = query.where(Address.house_corpus == house_corpus)
    return db.scalar(query)
