"""Таблицы проекта «Домовой».

Схема состоит из пяти основных сущностей — пользователи, адреса,
управляющие компании, отключения и обращения — и двух вспомогательных
таблиц: дома УК (привязка адреса к компании) и отметки об отправленных
уведомлениях.

Значения, которые повторяются в коде (типы отключений, статусы
обращений), вынесены в константы в начале файла. Сами колонки
строковые: новый тип отключения или статус добавляется константой
без правки схемы.

Описание схемы для разработчиков — в docs/DATABASE.md.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UTILITY_WATER = "water"
UTILITY_ELECTRICITY = "electricity"
UTILITY_TYPES = (UTILITY_WATER, UTILITY_ELECTRICITY)

APPEAL_STATUS_NEW = "new"
APPEAL_STATUS_SENT = "sent"
APPEAL_STATUS_IN_PROGRESS = "in_progress"
APPEAL_STATUS_RESOLVED = "resolved"
APPEAL_STATUS_FAILED = "failed"
APPEAL_STATUSES = (
    APPEAL_STATUS_NEW,
    APPEAL_STATUS_SENT,
    APPEAL_STATUS_IN_PROGRESS,
    APPEAL_STATUS_RESOLVED,
    APPEAL_STATUS_FAILED,
)


class Base(DeclarativeBase):
    """Общий базовый класс для всех таблиц."""


class User(Base):
    """Жилец сервиса: его аккаунт в мессенджере и настройки уведомлений.

    telegram_id пустой у тех, кто пользуется только сайтом.
    Настройки нужны, чтобы не слать то, что человека не интересует:
    например, только отключения электричества.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    notify_outages: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    notify_water: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    notify_electricity: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    appeals: Mapped[list["Appeal"]] = relationship(back_populates="user")
    notifications: Mapped[list["OutageNotification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id}>"


class Address(Base):
    """Адрес жильца: город, улица, дом и квартира.

    Дом хранится так же, как его разбирает app/services/addresses.py:
    номер отдельно (house_number) и корпус отдельно (house_corpus).
    Улица хранится в том виде, как её ввёл жилец, — нормализуется
    она при поиске отключений в app/services/matching.py.
    """

    __tablename__ = "addresses"
    __table_args__ = (
        # Один и тот же дом нельзя добавить жильцу дважды
        Index(
            "uq_addresses_user_place",
            "user_id",
            "city",
            "street",
            "house_number",
            text("coalesce(house_corpus, '')"),
            unique=True,
        ),
        Index("ix_addresses_place", "city", "street", "house_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    city: Mapped[str] = mapped_column(String(120))
    street: Mapped[str] = mapped_column(String(200))
    house_number: Mapped[int] = mapped_column(Integer)
    house_corpus: Mapped[str | None] = mapped_column(String(16))
    flat: Mapped[int | None] = mapped_column(Integer)
    # Адрес по умолчанию: о нём спрашиваем, когда жилец ещё не выбрал
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="addresses")
    appeals: Mapped[list["Appeal"]] = relationship(back_populates="address")

    def __repr__(self) -> str:
        return f"<Address id={self.id} {self.street}, {self.house_number}>"


class ManagementCompany(Base):
    """Управляющая компания — получатель обращений.

    Заполняется из справочника УК (data/companies.csv) парсером
    с сайта МинЖКХ.
    """

    __tablename__ = "management_companies"
    __table_args__ = (UniqueConstraint("name", "city", name="uq_companies_name_city"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    houses: Mapped[list["CompanyHouse"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    appeals: Mapped[list["Appeal"]] = relationship(back_populates="company")

    def __repr__(self) -> str:
        return f"<ManagementCompany id={self.id} {self.name}>"


class CompanyHouse(Base):
    """Дом, закреплённый за управляющей компанией.

    По этой таблице определяется, кому уходит обращение: ищем дом
    среди закреплённых за компанией.
    """

    __tablename__ = "company_houses"
    __table_args__ = (
        UniqueConstraint("company_id", "city", "street", "house_number", name="uq_company_houses_place"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE"), index=True
    )
    city: Mapped[str] = mapped_column(String(120))
    street: Mapped[str] = mapped_column(String(200))
    house_number: Mapped[int] = mapped_column(Integer)
    house_corpus: Mapped[str | None] = mapped_column(String(16))

    company: Mapped["ManagementCompany"] = relationship(back_populates="houses")

    def __repr__(self) -> str:
        return f"<CompanyHouse id={self.id} {self.street}, {self.house_number}>"


class Outage(Base):
    """Отключение воды или электричества, собранное с сайта поставщика.

    Адреса отключения хранятся так, как их отдал источник: город,
    улица и список домов строкой (houses_raw, например «1-15, 12к2»).
    Такой список — ключ от дублей при повторных проходах парсера,
    а разбирается он функцией parse_house_list из
    app/services/addresses.py.
    """

    __tablename__ = "outages"
    __table_args__ = (
        # Та же строка источника повторно в базу не попадает
        UniqueConstraint(
            "utility",
            "city",
            "street",
            "houses_raw",
            "starts_at",
            name="uq_outages_source_row",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    utility: Mapped[str] = mapped_column(String(32), index=True)
    city: Mapped[str] = mapped_column(String(120), index=True)
    street: Mapped[str] = mapped_column(String(200))
    houses_raw: Mapped[str] = mapped_column(String(500))
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    notifications: Mapped[list["OutageNotification"]] = relationship(
        back_populates="outage", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Outage id={self.id} {self.utility} {self.street}, {self.houses_raw}>"


class Appeal(Base):
    """Обращение жильца в управляющую компанию.

    user_id и company_id пустые, когда обращение пришло с сайта без
    аккаунта или для дома не нашлось УК: такое обращение всё равно
    сохраняем, чтобы его не потерять.
    """

    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Номер для письма и для жильца: DM-00001
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("management_companies.id", ondelete="SET NULL"), index=True
    )
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"), index=True
    )
    # Адрес текстом: обращение может прийти и без заведённого адреса
    address_text: Mapped[str] = mapped_column(String(400))
    subject: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(
        String(32), default=APPEAL_STATUS_NEW, server_default=APPEAL_STATUS_NEW, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User | None"] = relationship(back_populates="appeals")
    company: Mapped["ManagementCompany | None"] = relationship(back_populates="appeals")
    address: Mapped["Address | None"] = relationship(back_populates="appeals")

    def __repr__(self) -> str:
        return f"<Appeal id={self.id} {self.number} {self.status}>"


class OutageNotification(Base):
    """Отметка, что жилец уже получил сообщение об этом отключении.

    Нужна, чтобы при очередном проходе парсера не слать то же самое
    уведомление повторно. Удаляется вместе с отключением и с
    пользователем.
    """

    __tablename__ = "outage_notifications"
    __table_args__ = (UniqueConstraint("user_id", "outage_id", name="uq_notifications_user_outage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    outage_id: Mapped[int] = mapped_column(
        ForeignKey("outages.id", ondelete="CASCADE"), index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notifications")
    outage: Mapped["Outage"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:
        return f"<OutageNotification user_id={self.user_id} outage_id={self.outage_id}>"
