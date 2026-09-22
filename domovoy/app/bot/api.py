"""Обёртка над REST API сервиса. Бот не ходит в базу напрямую."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self._client = httpx.Client(timeout=20.0)

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:  # noqa: BLE001 — тело может быть не JSON
                detail = response.text
            raise ApiError(response.status_code, str(detail))
        if not response.content:
            return None
        return response.json()

    # --- пользователи ---

    def upsert_user(self, max_user_id: str, full_name: str | None = None) -> dict:
        return self._call(
            "POST", "/api/users", json={"max_user_id": max_user_id, "full_name": full_name}
        )

    def update_settings(self, user_id: int, **fields: Any) -> dict:
        return self._call("PATCH", f"/api/users/{user_id}/settings", json=fields)

    def add_address(self, user_id: int, city: str, street: str, house: str, flat: str | None) -> dict:
        return self._call(
            "POST",
            f"/api/users/{user_id}/addresses",
            json={"city": city, "street": street, "house": house, "flat": flat},
        )

    def delete_address(self, user_id: int, address_id: int) -> None:
        self._call("DELETE", f"/api/users/{user_id}/addresses/{address_id}")

    # --- отключения ---

    def outages_for_user(self, user_id: int) -> list[dict]:
        return self._call("GET", f"/api/outages/for-user/{user_id}")

    # --- обращения ---

    def company_by_address(self, street: str, house: str) -> dict | None:
        try:
            return self._call("GET", "/api/companies/by-address", params={"street": street, "house": house})
        except ApiError as error:
            if error.status_code == 404:
                return None
            raise

    def create_appeal(self, **payload: Any) -> dict:
        return self._call("POST", "/api/appeals", json=payload)

    def my_appeals(self, user_id: int) -> list[dict]:
        return self._call("GET", "/api/appeals/mine", params={"user_id": user_id})

    def upload_photo(self, filename: str, content: bytes, content_type: str = "image/jpeg") -> str:
        data = self._call(
            "POST", "/api/appeals/photo", files={"file": (filename, content, content_type)}
        )
        return data["photo_path"]

    def close(self) -> None:
        self._client.close()
