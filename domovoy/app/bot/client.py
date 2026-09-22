"""Тонкий клиент MAX Bot API.

Документация: https://dev.max.ru/docs-api
Встречаются два адреса API (botapi.max.ru и platform-api.max.ru) и два способа
передать токен, поэтому и адрес, и способ вынесены в настройки.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MaxClient:
    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        self.token = token or settings.max_bot_token
        self.base_url = (base_url or settings.max_api_base_url).rstrip("/")
        if not self.token:
            raise RuntimeError("Не задан MAX_BOT_TOKEN — получите токен в business.max.ru")
        self._client = httpx.Client(timeout=40.0)

    # --- служебное ---

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        """Возвращает (headers, params) в зависимости от режима авторизации."""
        if settings.max_auth_mode == "query":
            return {}, {"access_token": self.token}
        return {"Authorization": self.token}, {}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers, params = self._auth()
        params.update(kwargs.pop("params", {}) or {})
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            headers={**headers, **kwargs.pop("headers", {})},
            params=params,
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    # --- методы API ---

    def get_me(self) -> dict[str, Any]:
        """Информация о боте. Удобно для проверки токена."""
        return self._request("GET", "/me")

    def get_updates(self, marker: int | None = None, timeout: int = 30, limit: int = 100) -> dict[str, Any]:
        """Long polling: возвращает новые события."""
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        return self._request("GET", "/updates", params=params)

    def send_message(
        self,
        user_id: str | int,
        text: str,
        keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Отправляет сообщение пользователю, при необходимости с кнопками."""
        body: dict[str, Any] = {"text": text}
        if keyboard:
            body["attachments"] = [
                {"type": "inline_keyboard", "payload": {"buttons": keyboard}}
            ]
        return self._request("POST", "/messages", params={"user_id": user_id}, json=body)

    def answer_callback(self, callback_id: str, notification: str | None = None) -> dict[str, Any]:
        """Закрывает «часики» на нажатой кнопке."""
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        return self._request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    def download_file(self, url: str) -> bytes:
        """Скачивает вложение (например, фото к обращению)."""
        response = self._client.get(url)
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        self._client.close()
