"""Фоновая работа бота: отправка писем в УК и рассылка уведомлений.

Письмо уходит в отдельном потоке: SMTP может отвечать десятки секунд,
и всё это время бот продолжает отвечать остальным жильцам. Жилец сразу
видит «Обращение принято, отправляю…», а потом — результат.

Рассылка раз в NOTIFY_INTERVAL секунд забирает из API отключения и
новые статусы обращений, о которых жильцы ещё не знают, отправляет
сообщения и ставит отметки. Отметки хранятся в базе.
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from app.bot import api, keyboards, texts
from app.services import mailer

logger = logging.getLogger("domovoy.bot")

NOTIFY_INTERVAL = 30
EXTENSIONS = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}


@dataclass
class SendJob:
    user_id: int
    number: str
    company: dict
    category: str
    message: str
    address_text: str
    contact: str | None
    uk_link: str
    photos: list[str] = field(default_factory=list)


_jobs: "queue.Queue[SendJob]" = queue.Queue()
# ссылки на фото последних обращений — чтобы приложить их при повторной отправке
_photo_cache: dict[str, list[str]] = {}
_PHOTO_CACHE_LIMIT = 500


def enqueue_send(job: SendJob) -> None:
    if job.photos:
        if len(_photo_cache) >= _PHOTO_CACHE_LIMIT:
            _photo_cache.pop(next(iter(_photo_cache)))
        _photo_cache[job.number] = list(job.photos)
    _jobs.put(job)


def cached_photos(number: str) -> list[str]:
    return list(_photo_cache.get(number, []))


def _user_reason(error: Exception) -> str:
    if "нет адреса почты" in str(error):
        return "у управляющей компании нет почты в реестре ГИС ЖКХ"
    return "почтовый сервер не ответил"


def process_send(client, job: SendJob) -> bool:
    """Отправляет письмо, ставит статус и сообщает жильцу результат."""
    attachments, photos_failed = [], False
    for index, url in enumerate(job.photos, start=1):
        try:
            data, mime = client.download(url)
        except Exception as error:  # фото не должно мешать отправке обращения
            logger.warning("Не удалось скачать фото %s: %s", url, error)
            photos_failed = True
            continue
        attachments.append((f"photo-{index}.{EXTENSIONS.get(mime, 'jpg')}", data, mime))

    try:
        mailer.send_appeal(
            number=job.number,
            to_email=job.company.get("email"),
            company=job.company["name"],
            category=job.category,
            message=job.message,
            address=job.address_text,
            contact=job.contact,
            attachments=attachments,
            uk_link=job.uk_link,
        )
    except Exception as error:
        logger.error("Обращение %s не отправлено: %s", job.number, error)
        _set_status(job.number, "failed")
        reply = texts.APPEAL_SEND_FAILED.format(number=job.number, reason=_user_reason(error))
        client.send_message(job.user_id, reply, keyboards.resend_menu([job.number]))
        return False

    _set_status(job.number, "sent")
    logger.info("Обращение %s отправлено в %s. Страница для УК: %s", job.number, job.company["name"], job.uk_link)
    reply = texts.APPEAL_SENT.format(number=job.number, company=job.company["name"])
    if photos_failed:
        reply += texts.PHOTOS_LOST
    client.send_message(job.user_id, reply, keyboards.main_menu())
    return True


def _set_status(number: str, status: str) -> None:
    try:
        api.update_appeal_status(number, status)
    except api.ApiError as error:
        logger.error("Не удалось сохранить статус %s для %s: %s", status, number, error)


def notify_outages(client, now=None) -> int:
    """Рассылает уведомления об отключениях; возвращает число отправленных."""
    from app.bot.handlers import outage_alert_text

    sent = 0
    for item in api.pending_outage_notifications():
        try:
            client.send_message(int(item["max_user_id"]), outage_alert_text(item["address"], item["outage"], now))
        except Exception as error:
            # жилец мог заблокировать бота: не повторяем бесконечно, но и не падаем
            logger.warning("Уведомление об отключении %s не доставлено: %s", item["outage"]["id"], error)
        api.mark_outage_notified(item["outage"]["id"], item["user_id"])
        sent += 1
    return sent


def notify_appeal_updates(client) -> int:
    """Сообщает жильцам о статусах, которые поставила УК."""
    sent = 0
    for item in api.pending_appeal_updates():
        text = texts.APPEAL_STATUS_CHANGED.format(
            number=item["number"],
            subject=item["subject"],
            status=texts.STATUS_LABELS.get(item["status"], item["status"]),
        )
        if item.get("uk_comment"):
            text += texts.APPEAL_COMMENT.format(comment=item["uk_comment"])
        try:
            client.send_message(int(item["max_user_id"]), text, keyboards.main_menu())
        except Exception as error:
            logger.warning("Уведомление о статусе %s не доставлено: %s", item["number"], error)
        api.mark_appeal_notified(item["number"], item["status"])
        sent += 1
    return sent


def _send_loop(client_factory) -> None:
    client = client_factory()
    while True:
        job = _jobs.get()
        try:
            process_send(client, job)
        except Exception:
            logger.exception("Сбой при отправке обращения %s", job.number)


def _notify_loop(client_factory) -> None:
    client = client_factory()
    while True:
        for task in (notify_outages, notify_appeal_updates):
            try:
                task(client)
            except Exception as error:
                logger.warning("Рассылка %s не выполнена: %s", task.__name__, error)
        time.sleep(NOTIFY_INTERVAL)


def start(client_factory) -> None:
    """Запускает фоновые потоки; у каждого свой клиент MAX."""
    for target, name in ((_send_loop, "mail-sender"), (_notify_loop, "notifier")):
        threading.Thread(target=target, args=(client_factory,), name=name, daemon=True).start()
