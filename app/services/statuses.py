"""Смена статуса обращения — одна точка для бота, API и страницы УК."""
from sqlalchemy.orm import Session

from app.models import APPEAL_STATUS_RESOLVED, APPEAL_STATUS_SENT, Appeal
from app.timeutil import local_now


def change_status(db: Session, appeal: Appeal, new_status: str, comment: str | None = None) -> Appeal:
    """Ставит статус и время события; комментарий УК сохраняется, если он есть."""
    appeal.status = new_status
    if new_status == APPEAL_STATUS_SENT and appeal.sent_at is None:
        appeal.sent_at = local_now()
    if new_status == APPEAL_STATUS_RESOLVED and appeal.resolved_at is None:
        appeal.resolved_at = local_now()
    comment = (comment or "").strip()
    if comment:
        appeal.uk_comment = comment
        # новый комментарий при том же статусе жилец тоже должен увидеть
        appeal.notified_status = None
    db.commit()
    db.refresh(appeal)
    return appeal
