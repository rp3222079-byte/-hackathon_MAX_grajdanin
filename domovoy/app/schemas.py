"""Схемы запросов и ответов REST API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from app.models import AppealStatus, UtilityType


def _as_utc(value):
    """SQLite отдаёт время без пояса. Считаем его UTC и помечаем явно."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_as_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Пользователи ---


class UserUpsert(BaseModel):
    max_user_id: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class UserSettings(BaseModel):
    notify_water: bool | None = None
    notify_electricity: bool | None = None
    notify_hours_before: int | None = Field(default=None, ge=0, le=168)


class AddressOut(ORMModel):
    id: int
    city: str
    street: str
    house: str
    flat: str | None = None


class UserOut(ORMModel):
    id: int
    max_user_id: str | None = None
    full_name: str | None = None
    notify_water: bool
    notify_electricity: bool
    notify_hours_before: int
    addresses: list[AddressOut] = []


# --- Адреса ---


class AddressIn(BaseModel):
    city: str = Field(min_length=2, max_length=120)
    street: str = Field(min_length=2, max_length=200)
    house: str = Field(min_length=1, max_length=32)
    flat: str | None = Field(default=None, max_length=32)


# --- Управляющие компании ---


class CompanyOut(ORMModel):
    id: int
    name: str
    email: str
    phone: str | None = None
    website: str | None = None
    city: str


# --- Отключения ---


class OutageIn(BaseModel):
    utility: UtilityType
    city: str | None = None
    raw_addresses: str = Field(min_length=3)
    starts_at: UtcDatetime
    ends_at: UtcDatetime | None = None
    reason: str | None = None
    is_planned: bool = True
    source: str = "manual"


class OutageOut(ORMModel):
    id: int
    utility: UtilityType
    city: str
    raw_addresses: str
    starts_at: UtcDatetime
    ends_at: UtcDatetime | None = None
    reason: str | None = None
    is_planned: bool
    source: str


# --- Обращения ---


class AppealIn(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=5)
    city: str | None = None
    street: str | None = None
    house: str | None = None
    flat: str | None = None
    contact: str | None = Field(default=None, max_length=200)
    user_id: int | None = None
    max_user_id: str | None = None
    photo_path: str | None = None
    source: str = "web"


class AppealOut(ORMModel):
    id: int
    number: str
    category: str
    message: str
    address_text: str
    contact: str | None = None
    status: AppealStatus
    company: CompanyOut | None = None
    created_at: UtcDatetime
    sent_at: UtcDatetime | None = None
    source: str


class AppealStatusIn(BaseModel):
    status: AppealStatus
