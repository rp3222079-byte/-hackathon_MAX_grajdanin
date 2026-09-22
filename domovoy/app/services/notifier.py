"""Рассылка уведомлений об отключениях жильцам."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bot import texts
from app.db import SessionLocal
from app.models import Notification, Outage
from app.services.matching import already_notified, users_for_outage

logger = logging.getLogger(__name__)


def outage_to_dict(outage: Outage) -> dict:
    return {
        "id": outage.id,
        "utility": outage.utility.value,
        "raw_addresses": outage.raw_addresses,
        "starts_at": outage.starts_at,
        "ends_at": outage.ends_at,
        "reason": outage.reason,
        "is_planned": outage.is_planned,
    }


def notify_new_outages(max_client, db: Session | None = None) -> int:
    """Рассылает уведомления по отключениям, о которых ещё не писали.

    Возвращает количество отправленных сообщений.
    """
    own_session = db is None
    db = db or SessionLocal()
    sent = 0
    try:
        now = datetime.now(timezone.utc)
        outages = db.execute(select(Outage).order_by(Outage.created_at.desc()).limit(200)).scalars().all()
        for outage in outages:
            if outage.ends_at is not None:
                ends = outage.ends_at if outage.ends_at.tzinfo else outage.ends_at.replace(tzinfo=timezone.utc)
                if ends < now:
                    continue  # уже закончилось, жильцу это не нужно
            for user, address in users_for_outage(db, outage):
                if not user.max_user_id or already_notified(db, user.id, outage.id):
                    continue

                message = texts.notification_message(outage_to_dict(outage), address.short)
                delivered = True
                try:
                    max_client.send_message(user.max_user_id, message)
                except Exception:  # noqa: BLE001 — один недоставленный не ломает рассылку
                    logger.exception("Не доставлено пользователю %s", user.max_user_id)
                    delivered = False

                db.add(Notification(user_id=user.id, outage_id=outage.id, delivered=delivered))
                db.commit()
                if delivered:
                    sent += 1
        return sent
    finally:
        if own_session:
            db.close()
