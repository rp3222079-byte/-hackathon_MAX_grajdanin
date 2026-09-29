"""Настройки приложения. Читаются из переменных окружения и файла .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Локально SQLite, в Docker — PostgreSQL
    database_url: str = "sqlite:///./domovoy.db"

    # Общий ключ бота и API (заголовок X-API-Key). Пустой — проверка выключена,
    # так удобно в тестах и при локальной отладке
    api_token: str = ""

    # Внешний адрес API: из него собирается ссылка для УК в письме
    public_base_url: str = "http://localhost:8000"

    # Часовой пояс города: в нём заводятся отключения и показывается время жильцу
    timezone: str = "Asia/Novosibirsk"


settings = Settings()
