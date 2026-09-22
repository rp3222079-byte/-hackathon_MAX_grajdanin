"""Точка входа бота: long polling MAX + фоновая рассылка уведомлений.

Запуск:  python -m app.bot.main
"""
from __future__ import annotations

import logging
import threading
import time

from app.bot.api import ApiClient
from app.bot.client import MaxClient
from app.bot.handlers import BotLogic
from app.config import settings
from app.services.notifier import notify_new_outages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("domovoy.bot")

NOTIFY_INTERVAL_SECONDS = 60


def extract_message(update: dict) -> tuple[str, str, str | None, list] | None:
    """Достаёт (user_id, текст, имя, вложения) из события с сообщением."""
    message = update.get("message") or {}
    sender = (message.get("sender") or {}) or (update.get("user") or {})
    user_id = sender.get("user_id") or update.get("user_id")
    if user_id is None:
        return None

    body = message.get("body") or {}
    text = body.get("text") or message.get("text") or ""
    name = sender.get("name") or sender.get("first_name")
    attachments = body.get("attachments") or message.get("attachments") or []
    return str(user_id), text, name, attachments


def extract_callback(update: dict) -> tuple[str, str, str | None, str | None] | None:
    """Достаёт (user_id, payload, имя, callback_id) из нажатия кнопки."""
    callback = update.get("callback") or {}
    if not callback:
        return None
    sender = callback.get("user") or {}
    user_id = sender.get("user_id")
    if user_id is None:
        return None
    payload = callback.get("payload") or ""
    return str(user_id), payload, sender.get("name"), callback.get("callback_id")


def notification_loop(max_client: MaxClient) -> None:
    """Отдельный поток: регулярно разносит новые отключения подписчикам."""
    while True:
        try:
            sent = notify_new_outages(max_client)
            if sent:
                logger.info("Разослано уведомлений: %s", sent)
        except Exception:  # noqa: BLE001 — поток не должен умирать
            logger.exception("Ошибка в рассылке уведомлений")
        time.sleep(NOTIFY_INTERVAL_SECONDS)


def main() -> None:
    if not settings.max_bot_token:
        raise SystemExit("Не задан MAX_BOT_TOKEN. Скопируйте .env.example в .env и заполните токен.")

    max_client = MaxClient()
    api = ApiClient()
    logic = BotLogic(max_client, api)

    try:
        me = max_client.get_me()
        logger.info("Бот запущен: %s", me.get("name") or me)
    except Exception:  # noqa: BLE001 — токен или адрес API могут быть неверными
        logger.exception("Не удалось получить информацию о боте. Проверьте MAX_BOT_TOKEN и MAX_API_BASE_URL")
        raise

    threading.Thread(target=notification_loop, args=(max_client,), daemon=True).start()

    marker: int | None = None
    while True:
        try:
            response = max_client.get_updates(marker=marker, timeout=30)
        except Exception:  # noqa: BLE001 — сеть может моргнуть
            logger.exception("Не удалось получить обновления, повтор через 5 секунд")
            time.sleep(5)
            continue

        marker = response.get("marker", marker)
        for update in response.get("updates", []):
            try:
                handle_update(logic, max_client, update)
            except Exception:  # noqa: BLE001 — одно событие не должно ронять бота
                logger.exception("Ошибка обработки события %s", update.get("update_type"))


def handle_update(logic: BotLogic, max_client: MaxClient, update: dict) -> None:
    update_type = update.get("update_type", "")

    if "callback" in update_type or update.get("callback"):
        parsed = extract_callback(update)
        if not parsed:
            return
        user_id, payload, name, callback_id = parsed
        if callback_id:
            try:
                max_client.answer_callback(callback_id)
            except Exception:  # noqa: BLE001 — не критично
                logger.debug("Не удалось закрыть callback %s", callback_id)
        logic.handle_callback(user_id, payload, name)
        return

    if "message" in update_type or update.get("message"):
        parsed = extract_message(update)
        if not parsed:
            return
        user_id, text, name, attachments = parsed
        logic.handle_message(user_id, text, name, attachments)
        return

    if "bot_started" in update_type:
        user_id = str((update.get("user") or {}).get("user_id", ""))
        if user_id:
            logic.handle_message(user_id, "/start", (update.get("user") or {}).get("name"), [])


if __name__ == "__main__":
    main()
