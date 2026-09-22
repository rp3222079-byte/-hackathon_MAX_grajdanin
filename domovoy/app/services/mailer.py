"""Отправка обращений на почту управляющей компании."""
from __future__ import annotations

import logging
import mimetypes
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)
OUTBOX_DIR = Path("outbox")

BODY_TEMPLATE = """Здравствуйте!

Через сервис «Домовой» поступило обращение от жильца.

Номер обращения: {number}
Дата: {created}
Адрес: {address}
Категория: {category}
Контакт жильца: {contact}

Текст обращения:
{message}

--
Письмо отправлено автоматически сервисом «Домовой».
Ответьте на это письмо, чтобы связаться с жильцом.
"""


def build_message(
    *,
    number: str,
    to_email: str,
    address: str,
    category: str,
    contact: str | None,
    text: str,
    created_at: datetime | None = None,
    photo_path: str | None = None,
) -> EmailMessage:
    """Собирает письмо с обращением, при наличии прикладывает фото."""
    created = (created_at or datetime.now(timezone.utc)).strftime("%d.%m.%Y %H:%M")
    email = EmailMessage()
    email["Subject"] = f"[{number}] Обращение жильца: {category} — {address}"
    email["From"] = settings.smtp_from
    email["To"] = to_email
    email.set_content(
        BODY_TEMPLATE.format(
            number=number,
            created=created,
            address=address,
            category=category,
            contact=contact or "не указан",
            message=text,
        )
    )

    if photo_path:
        path = Path(photo_path)
        if path.exists():
            guessed, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (guessed or "application/octet-stream").split("/", 1)
            email.add_attachment(
                path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
            )
        else:
            logger.warning("Файл %s не найден, письмо уйдёт без вложения", photo_path)
    return email


def send_email(email: EmailMessage) -> None:
    """Отправляет письмо. В режиме SMTP_DRY_RUN складывает его в папку outbox/."""
    if settings.smtp_dry_run:
        OUTBOX_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = OUTBOX_DIR / f"{stamp}.eml"
        path.write_bytes(bytes(email))
        logger.info("SMTP_DRY_RUN: письмо сохранено в %s (получатель %s)", path, email["To"])
        return

    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(email)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(email)
    logger.info("Письмо %s отправлено на %s", email["Subject"], email["To"])
