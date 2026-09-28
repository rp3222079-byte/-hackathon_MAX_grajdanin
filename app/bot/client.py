import os
import requests

BASE_URL = os.getenv("MAX_API_BASE_URL", "https://platform-api.max.ru")


def to_inline_keyboard(keyboard):
    """[['Мой адрес'], ['Отключения']] -> вложение inline_keyboard для MAX.
    payload кнопки = её текст, поэтому нажатие обработается как обычный ввод."""
    buttons = [
        [{"type": "callback", "text": label, "payload": label} for label in row]
        for row in keyboard
    ]
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


class MaxClient:
    def __init__(self, token=None, base_url=BASE_URL):
        token = token or os.getenv("MAX_BOT_TOKEN")
        if not token:
            raise RuntimeError("MAX_BOT_TOKEN не задан (проверь .env)")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = token

    def _request(self, method, path, timeout=15, **kwargs):
        response = self.session.request(
            method, self.base_url + path, timeout=timeout, **kwargs
        )
        if not response.ok:
            raise RuntimeError(f"MAX API {response.status_code}: {response.text}")
        return response.json()

    def get_me(self):
        return self._request("GET", "/me")

    def get_updates(self, marker=None, timeout=30):
        params = {
            "timeout": timeout,
            "types": "message_created,message_callback,bot_started",
        }
        if marker is not None:
            params["marker"] = marker
        # HTTP-таймаут больше long-poll таймаута, иначе requests оборвёт ожидание
        return self._request("GET", "/updates", timeout=timeout + 10, params=params)

    def send_message(self, user_id, text, keyboard=None):
        body = {"text": text}
        if keyboard:
            body["attachments"] = [to_inline_keyboard(keyboard)]
        return self._request("POST", "/messages", params={"user_id": user_id}, json=body)

    def answer_callback(self, callback_id, notification="Принято"):
        # notification показывается пользователю коротким всплывающим уведомлением
        return self._request(
            "POST", "/answers",
            params={"callback_id": callback_id},
            json={"notification": notification},
        )