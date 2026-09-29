"""Настройки приложения. Читаются из переменных окружения и файла .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Локально SQLite, в Docker — PostgreSQL
    database_url: str = "sqlite:///./domovoy.db"


settings = Settings()
