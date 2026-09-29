"""Подключение к базе данных: движок, фабрика сессий, создание схемы.

Единственное место, где создаётся подключение к БД. Строка подключения
берётся из настроек (app/config.py), то есть из переменной DATABASE_URL.

Пример зависимости для роутера FastAPI:

    @router.get("/addresses")
    def list_addresses(db: Session = Depends(get_db)):
        ...
"""
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.migrations import run_migrations

# База в памяти: без StaticPool каждое соединение получало бы свою пустую базу
IN_MEMORY_URLS = ("sqlite://", "sqlite:///:memory:")


def create_db_engine(url: str | None = None) -> Engine:
    """Создаёт движок под указанную строку подключения."""
    url = url or settings.database_url

    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    if url in IN_MEMORY_URLS:
        options["poolclass"] = StaticPool

    engine = create_engine(url, **options)

    if url.startswith("sqlite"):
        # SQLite выключает внешние ключи по умолчанию, а на них завязаны каскады

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = create_db_engine()
SessionLocal = sessionmaker(
    bind=engine, class_=Session, autoflush=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Применяет миграции. Вызывается при старте API, бота и парсера."""
    run_migrations(engine)
