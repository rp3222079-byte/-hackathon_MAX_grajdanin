"""Схемы запросов и ответов API.

Схемы описывают то, что видит бот и сайт, и служат валидацией: всё, что
не прошло проверку, до базы не доходит. Ответы собираются из моделей
SQLAlchemy, поэтому у них включён from_attributes.

Примеры в полях (examples) попадают в /docs — по ним видно, как
выглядит типовой запрос.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    APPEAL_STATUS_FAILED,
    APPEAL_STATUS_IN_PROGRESS,
    APPEAL_STATUS_NEW,
    APPEAL_STATUS_RESOLVED,
    APPEAL_STATUS_SENT,
    UTILITY_ELECTRICITY,
    UTILITY_TYPES,
    UTILITY_WATER,
)

UtilityName = Literal[UTILITY_WATER, UTILITY_ELECTRICITY]
AppealStatus = Literal[
    APPEAL_STATUS_NEW,
    APPEAL_STATUS_SENT,
    APPEAL_STATUS_IN_PROGRESS,
    APPEAL_STATUS_RESOLVED,
    APPEAL_STATUS_FAILED,
]


class ORMModel(BaseModel):
    """Общая база схем, собираемых из моделей SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class UserCreate(BaseModel):
    """Регистрация жильца: тот же telegram_id возвращает прежнего жильца."""

    telegram_id: str | None = Field(
        default=None,
        max_length=64,
        examples=["1001"],
        description="Аккаунт в мессенджере MAX; пусто у тех, кто пользуется только сайтом.",
    )

    @field_validator("telegram_id")
    @classmethod
    def strip_telegram_id(cls, value: str | None) -> str | None:
        return _strip(value)


class UserUpdate(BaseModel):
    """Настройки уведомлений жильца."""

    notify_outages: bool | None = None
    notify_water: bool | None = None
    notify_electricity: bool | None = None
    notify_hours_before: int | None = Field(default=None, ge=0, le=72)


class UserOut(ORMModel):
    """Жилец с его адресами."""

    id: int
    telegram_id: str | None
    notify_outages: bool
    notify_water: bool
    notify_electricity: bool
    notify_hours_before: int
    created_at: datetime
    addresses: list["AddressOut"] = Field(default_factory=list)


class AddressCreate(BaseModel):
    """Адрес жильца: город, улица, дом и необязательные корпус и квартира."""

    city: str = Field(min_length=1, max_length=120, examples=["Новосибирск"])
    street: str = Field(min_length=1, max_length=200, examples=["ул. Ленина"])
    house_number: int = Field(ge=1, le=99999, examples=[11])
    house_corpus: str | None = Field(default=None, max_length=16, examples=["к2"])
    flat: int | None = Field(default=None, ge=1, le=99999)
    is_primary: bool = Field(default=False, description="Адрес по умолчанию для уведомлений.")

    @field_validator("city", "street")
    @classmethod
    def check_not_blank(cls, value: str) -> str:
        # пробелы по краям не мешают, а строка из одних пробелов — это не адрес
        if not value.strip():
            raise ValueError("значение не может состоять из пробелов")
        return value.strip()

    @field_validator("house_corpus")
    @classmethod
    def normalize_corpus(cls, value: str | None) -> str | None:
        """«2К» и «к2» — один и тот же корпус, приводим к виду «к2»."""
        corpus = _strip(value)
        if corpus is None:
            return None
        corpus = corpus.lower().replace(" ", "")
        digits = "".join(char for char in corpus if char.isdigit())
        letters = "".join(char for char in corpus if not char.isdigit())
        return f"{letters}{digits}"


class AddressOut(ORMModel):
    """Адрес в ответе API."""

    id: int
    user_id: int
    city: str
    street: str
    house_number: int
    house_corpus: str | None
    flat: int | None
    is_primary: bool
    created_at: datetime


class OutageOut(ORMModel):
    """Отключение: ресурс, адрес, время работ и причина."""

    id: int
    utility: str = Field(examples=list(UTILITY_TYPES))
    city: str
    street: str
    houses_raw: str = Field(description="Список домов строкой, например «1-15, 12к2».")
    starts_at: datetime
    ends_at: datetime | None
    source: str
    reason: str | None


class AppealCreate(BaseModel):
    """Обращение жильца в управляющую компанию.

    Адрес указывается либо заведённым адресом (address_id), либо текстом —
    на случай, когда жилец ещё не завёл адрес в профиле.
    """

    user_id: int | None = Field(default=None, ge=1)
    address_id: int | None = Field(default=None, ge=1)
    address_text: str | None = Field(
        default=None, max_length=400, examples=["Новосибирск, ул. Ленина, 11"]
    )
    subject: str = Field(min_length=1, max_length=200, examples=["Не горит свет в подъезде"])
    text: str = Field(min_length=1, max_length=5000, examples=["В подъезде не горит свет вторые сутки."])
    photo_path: str | None = Field(default=None, max_length=400)

    @field_validator("address_text", "subject", "text")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        stripped = _strip(value)
        # тема и текст обязательны, а адрес может быть пустым
        if stripped is None and value is not None:
            raise ValueError("значение не может состоять из пробелов")
        return stripped

    @model_validator(mode="after")
    def check_address(self) -> "AppealCreate":
        if not self.address_id and not self.address_text:
            raise ValueError("укажите address_id или address_text")
        return self


class AppealStatusUpdate(BaseModel):
    """Смена статуса обращения: ставит УК (или бот — после отправки письма)."""

    status: AppealStatus


class AppealOut(ORMModel):
    """Обращение: номер для жильца, статус и адрес."""

    id: int
    number: str = Field(examples=["DM-00001"])
    user_id: int | None
    company_id: int | None
    address_id: int | None
    address_text: str
    subject: str
    text: str
    photo_path: str | None
    status: str
    created_at: datetime
    sent_at: datetime | None
    resolved_at: datetime | None


UserOut.model_rebuild()

class CompanyOut(ORMModel):
    """Управляющая компания в ответе API."""

    id: int
    name: str
    email: str
    phone: str | None
    website: str | None
    city: str