"""Модели базы данных."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtilityType(str, enum.Enum):
    """Что отключают."""

    WATER_COLD = "water_cold"
    WATER_HOT = "water_hot"
    ELECTRICITY = "electricity"
    HEATING = "heating"
    GAS = "gas"


class AppealStatus(str, enum.Enum):
    """Жизненный цикл обращения жильца."""

    NEW = "new"
    SENT = "sent"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    FAILED = "failed"


class User(Base):
    """Житель, который пользуется ботом или сайтом."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(200))
    notify_water: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_electricity: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_hours_before: Mapped[int] = mapped_column(Integer, default=24)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    addresses: Mapped[list[Address]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    appeals: Mapped[list[Appeal]] = relationship(back_populates="user", lazy="selectin")


class Address(Base):
    """Адрес, по которому житель хочет получать уведомления."""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    city: Mapped[str] = mapped_column(String(120))
    street: Mapped[str] = mapped_column(String(200))
    house: Mapped[str] = mapped_column(String(32))
    flat: Mapped[str | None] = mapped_column(String(32))
    # Нормализованные значения для сопоставления с отключениями
    street_key: Mapped[str] = mapped_column(String(200), index=True)
    house_key: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="addresses")

    @property
    def short(self) -> str:
        text = f"{self.street}, д. {self.house}"
        if self.flat:
            text += f", кв. {self.flat}"
        return text


class ManagementCompany(Base):
    """Управляющая компания и её зона обслуживания."""

    __tablename__ = "management_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    served_houses: Mapped[list[ServedHouse]] = relationship(
        back_populates="company", cascade="all, delete-orphan", lazy="selectin"
    )


class ServedHouse(Base):
    """Дом, закреплённый за управляющей компанией."""

    __tablename__ = "served_houses"
    __table_args__ = (UniqueConstraint("company_id", "street_key", "house_key", name="uq_served_house"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE"), index=True
    )
    street_key: Mapped[str] = mapped_column(String(200), index=True)
    house_key: Mapped[str] = mapped_column(String(32), index=True)

    company: Mapped[ManagementCompany] = relationship(back_populates="served_houses")


class Outage(Base):
    """Отключение, собранное парсером или созданное вручную."""

    __tablename__ = "outages"

    id: Mapped[int] = mapped_column(primary_key=True)
    utility: Mapped[UtilityType] = mapped_column(Enum(UtilityType), index=True)
    city: Mapped[str] = mapped_column(String(120))
    raw_addresses: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(300), default="manual")
    # Хэш содержимого, чтобы парсер не заводил дубли
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    areas: Mapped[list[OutageArea]] = relationship(
        back_populates="outage", cascade="all, delete-orphan", lazy="selectin"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="outage", cascade="all, delete-orphan"
    )


class OutageArea(Base):
    """Разобранный адрес из отключения: одна улица и один дом."""

    __tablename__ = "outage_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    outage_id: Mapped[int] = mapped_column(ForeignKey("outages.id", ondelete="CASCADE"), index=True)
    street_key: Mapped[str] = mapped_column(String(200), index=True)
    house_key: Mapped[str] = mapped_column(String(32), index=True)

    outage: Mapped[Outage] = relationship(back_populates="areas")


class Notification(Base):
    """Отметка о том, что пользователю уже отправили это отключение."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "outage_id", name="uq_notification"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    outage_id: Mapped[int] = mapped_column(ForeignKey("outages.id", ondelete="CASCADE"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)

    outage: Mapped[Outage] = relationship(back_populates="notifications")


class Appeal(Base):
    """Обращение жильца в управляющую компанию."""

    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("management_companies.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    address_text: Mapped[str] = mapped_column(String(400))
    contact: Mapped[str | None] = mapped_column(String(200))
    photo_path: Mapped[str | None] = mapped_column(String(400))
    status: Mapped[AppealStatus] = mapped_column(Enum(AppealStatus), default=AppealStatus.NEW, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), default="web")  # web | max

    user: Mapped[User | None] = relationship(back_populates="appeals")
    company: Mapped[ManagementCompany | None] = relationship()

    @property
    def number(self) -> str:
        """Человекочитаемый номер обращения для письма и для жильца."""
        return f"DM-{self.id:05d}"
