"""Бот «Домовой» в MAX: приём событий long polling и запуск фоновых задач.

Запуск:

    python -m app.bot.main
"""
import logging
import time

from app.bot import api, handlers, keyboards, profiles, texts, workers
from app.bot.client import MaxClient
from app.env import load_env_file

logger = logging.getLogger("domovoy.bot")


def _attachments(body: dict) -> list[dict]:
    return (body or {}).get("attachments") or []


def parse_message(message: dict, user_id: int) -> handlers.Incoming:
    """Текст и вложения сообщения: фото, геолокация, контакт."""
    body = message.get("body") or {}
    incoming = handlers.Incoming(user_id=user_id, text=body.get("text") or "")
    for attachment in _attachments(body):
        kind = attachment.get("type")
        payload = attachment.get("payload") or {}
        if kind == "image" and payload.get("url"):
            incoming.photos.append(payload["url"])
        elif kind == "location" and "latitude" in attachment:
            incoming.location = (attachment["latitude"], attachment["longitude"])
        elif kind == "contact":
            incoming.contact = payload
    return incoming


def pressed_label(message: dict | None, payload: str) -> str | None:
    """Текст нажатой кнопки: ищем её в клавиатуре исходного сообщения."""
    for attachment in _attachments((message or {}).get("body")):
        if attachment.get("type") != "inline_keyboard":
            continue
        for row in (attachment.get("payload") or {}).get("buttons") or []:
            for button in row:
                if button.get("payload") == payload:
                    return button.get("text")
    return None


def handle_update(client: MaxClient, update: dict) -> None:
    kind = update.get("update_type")

    if kind == "bot_started":
        person = update["user"]
        incoming = handlers.Incoming(user_id=person["user_id"], text="/start")
    elif kind == "message_created":
        message = update["message"]
        recipient = message.get("recipient") or {}
        if recipient.get("chat_type") not in (None, "dialog"):
            return  # в групповых чатах бот не работает
        person = message["sender"]
        incoming = parse_message(message, person["user_id"])
    elif kind == "message_callback":
        callback = update["callback"]
        person = callback["user"]
        payload = callback.get("payload") or ""
        incoming = handlers.Incoming(user_id=person["user_id"], text=payload)
        original = update.get("message") or {}
        label = pressed_label(original, payload)
        original_text = ((original.get("body") or {}).get("text") or "").strip()
        try:
            if label and original_text:
                client.answer_callback(callback["callback_id"], message_text=f"{original_text}\n\n→ {label}")
            else:
                client.answer_callback(callback["callback_id"])
        except Exception as error:
            logger.warning("answer_callback: %s", error)
    else:
        return

    user_id = person["user_id"]
    profiles.remember(user_id, person.get("name"), person.get("username"))
    logger.info("[%s] user=%s text=%r photos=%s", kind, user_id, incoming.text[:60], len(incoming.photos))

    try:
        reply_text, reply_keyboard = handlers.route(incoming)
    except api.ApiError as error:
        logger.error("API ответил ошибкой: %s", error)
        if error.status == 404:
            api.forget_users()  # базу могли пересоздать — зарегистрируем жильца заново
        reply_text, reply_keyboard = texts.ERROR, keyboards.main_menu()
    except Exception:
        logger.exception("Сбой обработки сообщения")
        reply_text, reply_keyboard = texts.ERROR, keyboards.main_menu()
    client.send_message(user_id, reply_text, reply_keyboard)


def run() -> None:
    load_env_file()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")

    client = MaxClient()
    me = client.get_me()
    logger.info("Бот запущен: %s (@%s)", me.get("name") or me.get("first_name"), me.get("username"))
    try:
        client.set_commands(texts.COMMANDS)
    except Exception as error:
        logger.warning("Не удалось задать команды бота: %s", error)

    workers.start(MaxClient)

    marker = None
    while True:
        try:
            data = client.get_updates(marker=marker, timeout=30)
        except Exception as error:
            logger.warning("get_updates: %s", error)
            time.sleep(5)
            continue

        marker = data.get("marker", marker)
        for update in data.get("updates", []):
            try:
                handle_update(client, update)
            except Exception:
                logger.exception("Сбой обработки события")


if __name__ == "__main__":
    run()
