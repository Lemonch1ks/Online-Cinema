"""Migrations on a real PostgreSQL: the full cycle and no drift between models and migrations.

Each test uses its own throwaway database, the per-worker test database is not touched.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.core.config import settings, to_sync_url
from src.tests.db import alembic, create_database, drop_database, with_database


@pytest.fixture()
def empty_database(worker_id: str):
    base_name = make_url(settings.TEST_DATABASE_URL).database
    url = with_database(settings.TEST_DATABASE_URL, f"{base_name}_migrations_{worker_id}")
    create_database(url)
    yield url
    drop_database(url)


def query(url: str, sql: str) -> list:
    engine = create_engine(to_sync_url(url))
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).scalars().all()
    engine.dispose()
    return rows


USER_TABLES = "select table_name from information_schema.tables where table_schema = 'public' order by 1"
ENUM_TYPES = "select typname from pg_type where typtype = 'e' order by 1"


def test_upgrade_downgrade_upgrade_cycle(empty_database):
    alembic(empty_database, ("upgrade", "head"))
    assert query(empty_database, "select name::text from user_groups order by id") == ["USER", "MODERATOR", "ADMIN"]

    alembic(empty_database, ("downgrade", "base"))
    assert query(empty_database, USER_TABLES) == ["alembic_version"]
    assert query(empty_database, ENUM_TYPES) == []

    alembic(empty_database, ("upgrade", "head"))
    assert query(empty_database, "select count(*) from user_groups") == [3]


def test_downgrade_refuses_to_remove_groups_that_users_belong_to(empty_database):
    alembic(empty_database, ("upgrade", "head"))
    engine = create_engine(to_sync_url(empty_database))
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into users (email, hashed_password, is_active, group_id) "
                "values ('kept@example.com', 'x', true, (select id from user_groups where name = 'USER'))"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="users"):
        alembic(empty_database, ("downgrade", "base"))

    assert query(empty_database, "select version_num from alembic_version") == ["5b1c7e9d2a40"]
    assert query(empty_database, "select count(*) from user_groups") == [3]
    assert query(empty_database, "select email from users") == ["kept@example.com"]


def test_models_match_migrations(empty_database):
    """`alembic check` fails if autogenerate would create a new migration: someone changed a model
    and forgot the migration (or the other way round)."""
    alembic(empty_database, ("upgrade", "head"), ("check",))
