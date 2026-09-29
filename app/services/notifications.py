"""Что бот должен сообщить жильцам: отключения и новые статусы обращений.

Решение «кому и что отправить» принимает API, а бот только доставляет
сообщение и ставит отметку. Отметки хранятся в базе, поэтому после
перезапуска бота никто не получит одно уведомление дважды и ничего
не потеряется.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    APPEAL_STATUS_IN_PROGRESS,
    APPEAL_STATUS_RESOLVED,
    UTILITY_ELECTRICITY,
    UTILITY_WATER,
    Address,
    Appeal,
    Outage,
    OutageNotification,
    User,
)
from app.services.appeals import format_address_text
from app.services.matching import outage_covers
from app.timeutil import local_now

# Статусы, которые ставит УК: о них жилец узнаёт от бота.
# sent и failed бот показывает сам сразу после отправки письма.
STATUSES_FROM_COMPANY = (APPEAL_STATUS_IN_PROGRESS, APPEAL_STATUS_RESOLVED)

# Дальше этого горизонта отключения не рассматриваем вовсе
MAX_HOURS_BEFORE = 72


@dataclass
class PendingOutageNotification:
    user: User
    address: Address
    outage: Outage


def _wants(user: User, outage: Outage) -> bool:
    if not user.notify_outages:
        return False
    if outage.utility == UTILITY_WATER:
        return user.notify_water
    if outage.utility == UTILITY_ELECTRICITY:
        return user.notify_electricity
    return True


def _affected_address(user: User, outage: Outage) -> Address | None:
    """Адрес жильца, который задевает отключение; основной — в приоритете."""
    addresses = sorted(user.addresses, key=lambda address: (not address.is_primary, address.id))
    for address in addresses:
        if outage_covers(
            outage.city,
            outage.street,
            outage.houses_raw,
            city=address.city,
            street=address.street,
            house_number=address.house_number,
            house_corpus=address.house_corpus,
        ):
            return address
    return None


def pending_outage_notifications(
    db: Session, now: datetime | None = None
) -> list[PendingOutageNotification]:
    """Отключения, о которых пора предупредить жильцов.

    Жилец получает сообщение, когда до начала осталось не больше
    notify_hours_before часов (или отключение уже идёт), если этот ресурс
    у него включён и о таком отключении он ещё не слышал.
    """
    now = now or local_now()
    outages = db.scalars(
        select(Outage).where(
            or_(Outage.ends_at.is_(None), Outage.ends_at > now),
            Outage.starts_at <= now + timedelta(hours=MAX_HOURS_BEFORE),
        )
    ).all()
    if not outages:
        return []

    users = db.scalars(
        select(User)
        .where(User.max_user_id.is_not(None), User.notify_outages.is_(True))
        .options(selectinload(User.addresses))
    ).all()
    already = set(db.execute(select(OutageNotification.user_id, OutageNotification.outage_id)).all())

    pending: list[PendingOutageNotification] = []
    for user in users:
        window = timedelta(hours=user.notify_hours_before)
        for outage in outages:
            if (user.id, outage.id) in already or not _wants(user, outage):
                continue
            if outage.starts_at - now > window:
                continue
            address = _affected_address(user, outage)
            if address is not None:
                pending.append(PendingOutageNotification(user, address, outage))
    return pending


def mark_outage_notified(db: Session, user_id: int, outage_id: int) -> None:
    """Отметка «жилец уведомлён»; повторная отметка не ошибка."""
    db.add(OutageNotification(user_id=user_id, outage_id=outage_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def pending_appeal_updates(db: Session) -> list[Appeal]:
    """Обращения, у которых УК сменила статус, а жилец об этом ещё не знает."""
    appeals = db.scalars(
        select(Appeal)
        .join(User, Appeal.user_id == User.id)
        .where(User.max_user_id.is_not(None), Appeal.status.in_(STATUSES_FROM_COMPANY))
        .options(selectinload(Appeal.user), selectinload(Appeal.company))
        .order_by(Appeal.id)
    ).all()
    return [appeal for appeal in appeals if appeal.notified_status != appeal.status]


def address_line(address: Address) -> str:
    return format_address_text(address)
