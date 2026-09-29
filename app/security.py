"""Защита API.

Все JSON-эндпоинты доступны только с заголовком X-API-Key, равным API_TOKEN:
ими пользуется бот, а не жильцы напрямую. Страница обращения для УК
открывается по ссылке из письма и проверяется подписью, без ключа.
"""
import hashlib
import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Значение переменной API_TOKEN. Нужно, если она задана.",
)

# Запасной секрет подписи для локальной отладки без API_TOKEN
DEV_LINK_SECRET = "domovoy-local-dev"


def require_api_key(key: str | None = Security(api_key_header)) -> None:
    """Зависимость FastAPI: пропускает запрос только с верным ключом."""
    expected = settings.api_token
    if not expected:
        return
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен заголовок X-API-Key со значением API_TOKEN",
        )


def _link_secret() -> bytes:
    return (settings.api_token or DEV_LINK_SECRET).encode("utf-8")


def appeal_signature(number: str) -> str:
    """Подпись ссылки на обращение: без неё страницу УК не открыть."""
    digest = hmac.new(_link_secret(), number.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]


def check_appeal_signature(number: str, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(appeal_signature(number), signature)


def appeal_link(number: str) -> str:
    """Ссылка для УК: открыть обращение и поменять его статус."""
    base = settings.public_base_url.rstrip("/")
    return f"{base}/uk/appeals/{number}?sig={appeal_signature(number)}"
