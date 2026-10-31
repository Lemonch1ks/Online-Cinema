from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import database
from src.core.config import settings


# --- config ---

@pytest.mark.parametrize(
    ("async_url", "sync_url"),
    [
        ("sqlite+aiosqlite:///cinema.db", "sqlite:///cinema.db"),
        ("postgresql+asyncpg://user:pass@db:5432/cinema", "postgresql+psycopg://user:pass@db:5432/cinema"),
        ("mysql+pymysql://user:pass@db/cinema", "mysql+pymysql://user:pass@db/cinema"),  # unknown driver kept as is
    ],
)
def test_sync_database_url(async_url, sync_url):
    # Alembic runs synchronously, so it needs a sync driver; the password must survive the conversion
    assert settings.model_copy(update={"DATABASE_URL": async_url}).SYNC_DATABASE_URL == sync_url


def test_database_url_defaults_to_sqlite_file():
    fresh = type(settings)(DATABASE_URL="")

    assert fresh.DATABASE_URL == f"sqlite+aiosqlite:///{fresh.DB_PATH.as_posix()}"


def test_link_endpoints_are_built_from_base_url():
    assert settings.ACTIVATION_LINK_ENDPOINT == settings.APP_BASE_URL + settings.ACTIVATION_LINK_BASE
    assert settings.PASSWORD_RESET_LINK_ENDPOINT == settings.APP_BASE_URL + settings.PASSWORD_RESET_LINK_BASE
    assert settings.LOGIN_LINK_ENDPOINT == f"{settings.APP_BASE_URL}{settings.SECURITY_TOKEN_URL}/token"


# --- database ---

async def test_get_db_yields_session_and_closes_it():
    generator = database.get_db()
    session = await anext(generator)

    assert isinstance(session, AsyncSession)
    await generator.aclose()


def test_enable_sqlite_foreign_keys_skips_other_dialects():
    # a non-sqlite engine has no sync_engine here: touching it would raise AttributeError
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    database.enable_sqlite_foreign_keys(fake_engine)


async def test_sqlite_foreign_keys_are_enforced(db_session):
    result = await db_session.execute(text("PRAGMA foreign_keys"))

    assert result.scalar() == 1
