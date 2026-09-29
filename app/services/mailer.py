"""Письмо с обращением в управляющую компанию.

Письмо отправляет бот сразу после подтверждения обращения. Режимы:

* SMTP_DRY_RUN=true — письмо не уходит, а сохраняется в outbox/*.eml;
* MAIL_REDIRECT_TO=адрес — все письма уходят на этот адрес вместо почты УК
  (демонстрация без писем настоящим компаниям);
* иначе — на почту УК из реестра ГИС ЖКХ.
"""
import html
import os
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from app.timeutil import local_now

OUTBOX_DIR = Path("outbox")


class MailError(Exception):
    """Письмо не удалось отправить."""


def _settings():
    # читаем при каждом вызове, а не при импорте, чтобы .env успел загрузиться
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("SMTP_FROM") or os.getenv("SMTP_USER", ""),
        "reply_to": os.getenv("SMTP_REPLY_TO", ""),
        "dry_run": os.getenv("SMTP_DRY_RUN", "false").lower() == "true",
        "redirect_to": os.getenv("MAIL_REDIRECT_TO", "").strip(),
    }


def build_appeal_email(*, number, sender, to_email, company, category, message,
                       address, contact=None, reply_to=None, attachments=None,
                       uk_link=None, original_to=None):
    """attachments: список (имя_файла, байты, 'image/jpeg').

    uk_link — страница обращения для УК, где она ставит «В работе» или «Решено».
    original_to — настоящая почта УК, если письмо перенаправлено (MAIL_REDIRECT_TO).
    """
    contact_text = contact or "не указан"
    created = local_now().strftime("%d.%m.%Y %H:%M")
    photos = len(attachments or [])
    redirect_note = (
        f"Демонстрационный режим: письмо предназначалось {original_to}.\n\n" if original_to else ""
    )
    if uk_link:
        how_to_answer = (
            "Как ответить жильцу: откройте ссылку и отметьте «В работе» или «Решено»,\n"
            "при желании с комментарием — жилец сразу получит его в MAX.\n"
            f"{uk_link}\n"
        )
    else:
        how_to_answer = "Ответ можно направить на адрес отправителя, указав номер обращения.\n"

    msg = EmailMessage()
    msg["Subject"] = f"Обращение №{number}: {category}"
    msg["From"] = sender
    msg["To"] = to_email
    msg["Reply-To"] = reply_to or sender
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    # простой текст: запасной вариант для клиентов без HTML
    msg.set_content(
        f"{redirect_note}"
        f"Обращение №{number}\n"
        f"{'=' * 30}\n\n"
        f"Кому: {company}\n"
        f"Дата: {created}\n"
        f"Адрес: {address}\n"
        f"Категория: {category}\n"
        f"Контакт жильца: {contact_text}\n"
        f"Фото: {photos or 'нет'}\n\n"
        f"Текст обращения:\n{message}\n\n"
        f"{'-' * 30}\n"
        f"{how_to_answer}"
        f"\nОбращение передано через бота «Домовой» в MAX.\n"
    )

    # оформленная версия; всё, что ввёл жилец, экранируем
    e = html.escape
    row = 'style="padding:6px 12px 6px 0;color:#666;vertical-align:top"'
    redirect_html = (
        '<p style="background:#fff4d6;padding:8px 12px;border-radius:6px">'
        f"Демонстрационный режим: письмо предназначалось {e(original_to)}.</p>"
        if original_to else ""
    )
    if uk_link:
        answer_html = (
            "<b>Как ответить жильцу.</b> Откройте обращение и отметьте «В работе» или «Решено», "
            "при желании с комментарием — жилец сразу получит его в MAX.<br>"
            f'<a href="{e(uk_link)}" style="display:inline-block;margin-top:10px;padding:10px 16px;'
            'background:#1a7f8e;color:#fff;border-radius:6px;text-decoration:none">'
            f"Открыть обращение №{number}</a>"
        )
    else:
        answer_html = "Ответ можно направить на адрес отправителя, указав номер обращения."
    msg.add_alternative(
        f"""\
<div style="font-family:Arial,sans-serif;max-width:600px;color:#222">
  {redirect_html}
  <h2 style="margin:0 0 12px">Обращение №{number}</h2>
  <table style="border-collapse:collapse;width:100%">
    <tr><td {row}>Кому</td><td>{e(company)}</td></tr>
    <tr><td {row}>Дата</td><td>{created}</td></tr>
    <tr><td {row}>Адрес</td><td><b>{e(address)}</b></td></tr>
    <tr><td {row}>Категория</td><td>{e(category)}</td></tr>
    <tr><td {row}>Контакт жильца</td><td>{e(contact_text)}</td></tr>
    <tr><td {row}>Фото</td><td>{photos or "нет"}</td></tr>
  </table>
  <h3 style="margin:16px 0 6px">Текст обращения</h3>
  <p style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:6px;margin:0">{e(message)}</p>
  <div style="margin-top:16px;padding:12px 14px;border-left:4px solid #1a7f8e;background:#eef7f8">
    {answer_html}
  </div>
  <p style="color:#888;font-size:12px;margin-top:16px">Обращение передано через бота «Домовой» в MAX.</p>
</div>""",
        subtype="html",
    )

    for filename, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def _save_to_outbox(msg):
    OUTBOX_DIR.mkdir(exist_ok=True)
    path = OUTBOX_DIR / f"{datetime.now():%Y%m%d-%H%M%S-%f}.eml"
    path.write_bytes(bytes(msg))
    print(f"[dry-run] письмо «{msg['Subject']}» для {msg['To']} сохранено: {path}", flush=True)
    return path


def _send_once(msg, cfg):
    context = ssl.create_default_context()
    if cfg["port"] == 465:
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=20)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
    with server:
        if cfg["port"] != 465:
            server.starttls(context=context)
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def send_email(msg, attempts=3, delay=2):
    cfg = _settings()

    if cfg["dry_run"]:
        _save_to_outbox(msg)
        return

    if not (cfg["host"] and cfg["user"] and cfg["password"]):
        raise MailError("SMTP не настроен: проверь SMTP_HOST/SMTP_USER/SMTP_PASSWORD в .env")

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            _send_once(msg, cfg)
            return
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as error:
            # неверный пароль или адрес получателя: повтор ничего не изменит
            raise MailError(f"SMTP отказал: {error}") from error
        except (smtplib.SMTPException, OSError) as error:
            last_error = error
            print(f"SMTP попытка {attempt}/{attempts} не удалась: {error}", flush=True)
            if attempt < attempts:
                time.sleep(delay * attempt)

    raise MailError(f"Не удалось отправить письмо после {attempts} попыток: {last_error}")


def send_appeal(*, number, to_email, company, category, message, address,
                contact=None, attachments=None, uk_link=None):
    if not (to_email or "").strip():
        # У части организаций в реестре ГИС ЖКХ почты нет, и парсер
        # оставляет поле пустым, а не выдумывает адрес. Отправлять
        # письмо некуда, поэтому говорим об этом прямо, а не роняем
        # SMTP на пустом адресе.
        raise MailError(f"у компании «{company}» нет адреса почты в реестре ГИС ЖКХ")
    cfg = _settings()
    sender = cfg["sender"] or "no-reply@domovoy.local"
    recipient = cfg["redirect_to"] or to_email
    msg = build_appeal_email(
        number=number, sender=sender, to_email=recipient, company=company,
        category=category, message=message, address=address, contact=contact,
        reply_to=cfg["reply_to"] or sender, attachments=attachments,
        uk_link=uk_link, original_to=to_email if cfg["redirect_to"] else None,
    )
    send_email(msg)

