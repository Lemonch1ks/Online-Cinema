from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from src.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

sync_engine = create_engine(settings.SYNC_DATABASE_URL, echo=settings.DB_ECHO, poolclass=NullPool)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
