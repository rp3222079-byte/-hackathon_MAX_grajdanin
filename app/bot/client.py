"""Клиент MAX Bot API: получение событий и отправка сообщений.

Документация: https://dev.max.ru/docs-api, схема —
https://github.com/max-messenger/api-schema. Авторизация — заголовок
Authorization с токеном бота.
"""
import logging
import os

import requests

from app.bot.tls import ca_bundle_path

logger = logging.getLogger("domovoy.bot")

DEFAULT_BASE_URL = "https://platform-api2.max.ru"
MAX_TEXT_LENGTH = 4000
# Кнопки, которые запрашивают данные устройства: если клиент MAX или API
# их не примет, сообщение переотправляется без них
DEVICE_BUTTONS = ("request_contact", "request_geo_location")


class MaxApiError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"MAX API {status}: {text}")
        self.status = status


def callback_button(text: str, payload: str | None = None) -> dict:
    return {"type": "callback", "text": text[:128], "payload": (payload or text)[:1024]}


def contact_button(text: str) -> dict:
    return {"type": "request_contact", "text": text[:128]}


def geo_button(text: str) -> dict:
    return {"type": "request_geo_location", "text": text[:128]}


def to_inline_keyboard(keyboard: list[list]) -> dict:
    """[['Мой адрес'], [кнопка-словарь]] → вложение inline_keyboard.

    Строка превращается в callback-кнопку, payload которой равен тексту:
    нажатие обрабатывается так же, как ввод этого текста.
    """
    buttons = [
        [item if isinstance(item, dict) else callback_button(item) for item in row]
        for row in keyboard
        if row
    ]
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


def without_device_buttons(keyboard: list[list]) -> list[list]:
    rows = [
        [item for item in row if not (isinstance(item, dict) and item.get("type") in DEVICE_BUTTONS)]
        for row in keyboard
    ]
    return [row for row in rows if row]


def has_device_buttons(keyboard: list[list] | None) -> bool:
    return bool(keyboard) and any(
        isinstance(item, dict) and item.get("type") in DEVICE_BUTTONS for row in keyboard for item in row
    )


class MaxClient:
    def __init__(self, token: str | None = None, base_url: str | None = None):
        token = token or os.getenv("MAX_BOT_TOKEN")
        if not token:
            raise RuntimeError("MAX_BOT_TOKEN не задан (проверьте .env)")
        self.base_url = (base_url or os.getenv("MAX_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = token
        self.session.verify = ca_bundle_path()

    def _request(self, method: str, path: str, timeout: float = 15, **kwargs):
        response = self.session.request(method, self.base_url + path, timeout=timeout, **kwargs)
        if not response.ok:
            raise MaxApiError(response.status_code, response.text[:500])
        return response.json() if response.content else {}

    def get_me(self) -> dict:
        return self._request("GET", "/me")

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        body = {"commands": [{"name": name, "description": text} for name, text in commands]}
        self._request("PATCH", "/me/commands", json=body)

    def get_updates(self, marker: int | None = None, timeout: int = 30) -> dict:
        params = {
            "timeout": timeout,
            "types": "message_created,message_callback,bot_started",
        }
        if marker is not None:
            params["marker"] = marker
        # HTTP-таймаут больше long-poll таймаута, иначе requests оборвёт ожидание
        return self._request("GET", "/updates", timeout=timeout + 10, params=params)

    def send_message(self, user_id: int, text: str, keyboard: list[list] | None = None) -> dict:
        body: dict = {"text": text[:MAX_TEXT_LENGTH]}
        if keyboard:
            body["attachments"] = [to_inline_keyboard(keyboard)]
        try:
            return self._request("POST", "/messages", params={"user_id": user_id}, json=body)
        except MaxApiError as error:
            if error.status != 400 or not has_device_buttons(keyboard):
                raise
            logger.warning("MAX не принял кнопки контакта/геолокации, отправляю без них: %s", error)
            return self.send_message(user_id, text, without_device_buttons(keyboard))

    def answer_callback(self, callback_id: str, *, message_text: str | None = None,
                        notification: str = "Принято") -> dict:
        """Ответ на нажатие кнопки.

        С message_text исходное сообщение переписывается без клавиатуры:
        в истории остаётся выбранный вариант, а старые кнопки нельзя
        нажать повторно. Если MAX не принял правку, показываем уведомление.
        """
        params = {"callback_id": callback_id}
        if message_text:
            body = {"message": {"text": message_text[:MAX_TEXT_LENGTH], "attachments": []}}
            try:
                return self._request("POST", "/answers", params=params, json=body)
            except MaxApiError as error:
                logger.warning("Не удалось обновить сообщение с кнопками: %s", error)
        return self._request("POST", "/answers", params=params, json={"notification": notification})

    def download(self, url: str, max_bytes: int = 10 * 1024 * 1024) -> tuple[bytes, str]:
        """Скачивает вложение (фото) по ссылке из сообщения: байты и MIME-тип."""
        response = requests.get(url, timeout=20, verify=ca_bundle_path(), stream=True)
        response.raise_for_status()
        data = b""
        for chunk in response.iter_content(64 * 1024):
            data += chunk
            if len(data) > max_bytes:
                raise ValueError("файл слишком большой")
        mime = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return data, mime if mime.startswith("image/") else "image/jpeg"
