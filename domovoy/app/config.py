"""Настройки приложения. Читаются из переменных окружения и файла .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # База данных
    database_url: str = "sqlite:///./domovoy.db"

    # REST API
    api_base_url: str = "http://localhost:8000"

    # Бот MAX
    max_bot_token: str = ""
    max_api_base_url: str = "https://platform-api.max.ru"
    max_auth_mode: str = "header"  # header | query

    # Парсер
    parser_source_url: str = ""
    parser_interval_seconds: int = 1800
    default_city: str = "Москва"
    # Часовой пояс, в котором сайт-источник публикует время, и в котором пишет бот
    timezone: str = "Europe/Moscow"

    # Почта
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "domovoy@example.ru"
    smtp_use_tls: bool = True
    smtp_dry_run: bool = True

    # Админка
    admin_token: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
