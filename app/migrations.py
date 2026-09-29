"""Миграции схемы БД.

Схема меняется миграциями — по очереди, по номеру версии. Каждая
миграция это функция, которая получает Connection и меняет схему.
Номера уже применённых миграций хранятся в служебной таблице
schema_migrations, поэтому повторный запуск ничего не ломает.

Как добавить миграцию:

    @migration(2, "add_appeals_photo")
    def add_appeals_photo(conn: Connection) -> None:
        conn.execute(text("ALTER TABLE appeals ADD COLUMN photo_size INTEGER"))

Номер и название должны быть новыми, а сама функция — идемпотентной
настолько, насколько позволяет СУБД.

Запуск:

    python -m app.migrations            # применить недостающие
    python -m app.migrations --status   # показать, что уже применено

Полноценные миграции Alembic — следующий шаг после хакатона,
см. раздел «Что доделать после хакатона» в README.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    func,
    select,
)

from app.models import Base

MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = []


def migration(
    version: int, name: str
) -> Callable[[Callable[[Connection], None]], Callable[[Connection], None]]:
    def decorator(func: Callable[[Connection], None]) -> Callable[[Connection], None]:
        MIGRATIONS.append((version, name, func))
        return func

    return decorator


SCHEMA_MIGRATIONS = Table(
    "schema_migrations",
    MetaData(),
    Column("version", Integer, primary_key=True),
    Column("name", String(200), nullable=False),
    Column("applied_at", DateTime, server_default=func.now(), nullable=False),
)


@migration(1, "initial_schema")
def initial_schema(conn: Connection) -> None:
    """Создаёт таблицы, описанные в app/models.py."""
    Base.metadata.create_all(conn)


def applied_versions(conn: Connection) -> set[int]:
    """Номера уже применённых миграций."""
    SCHEMA_MIGRATIONS.create(conn, checkfirst=True)
    rows = conn.execute(select(SCHEMA_MIGRATIONS.c.version))
    return {row[0] for row in rows}


def run_migrations(engine) -> list[tuple[int, str]]:
    """Применяет недостающие миграции, возвращает список применённых."""
    applied: list[tuple[int, str]] = []
    with engine.begin() as conn:
        done = applied_versions(conn)
        for version, name, func in sorted(MIGRATIONS, key=lambda item: item[0]):
            if version in done:
                continue
            func(conn)
            conn.execute(SCHEMA_MIGRATIONS.insert().values(version=version, name=name))
            applied.append((version, name))
    return applied


def migration_status(engine) -> list[tuple[int, str, bool]]:
    """Список всех миграций с отметкой, применена ли она."""
    with engine.connect() as conn:
        done = applied_versions(conn)
    return [
        (version, name, version in done)
        for version, name, _ in sorted(MIGRATIONS, key=lambda item: item[0])
    ]


def main() -> None:
    from app.db import engine

    parser = argparse.ArgumentParser(description="Миграции схемы БД")
    parser.add_argument(
        "--status",
        action="store_true",
        help="показать состояние миграций, ничего не применяя",
    )
    args = parser.parse_args()

    if args.status:
        for version, name, applied in migration_status(engine):
            mark = "применена" if applied else "не применена"
            print(f"{version:>4}  {name:<24} {mark}")
        return

    applied = run_migrations(engine)
    if applied:
        for version, name in applied:
            print(f"применена миграция {version} ({name})")
    else:
        print("схема уже актуальна")


if __name__ == "__main__":
    main()
