"""Подключение к базе данных.

engine      — "соединение" SQLAlchemy с конкретной БД.
SessionLocal — фабрика сессий; одна сессия = одна единица работы с БД.
Base        — родительский класс для всех ORM-моделей.
get_db      — зависимость FastAPI: выдаёт сессию на время запроса и закрывает её.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# check_same_thread нужен только SQLite: FastAPI обрабатывает запросы в разных потоках
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db  # код эндпоинта выполняется здесь
    finally:
        db.close()  # сессия закроется даже если эндпоинт упал с ошибкой
