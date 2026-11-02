"""Celery tasks: called directly, no Redis or worker needed."""
import logging

import pytest
from celery.schedules import crontab
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import src.tasks
from src.auth.models import ActivationToken
from src.core.config import to_sync_url
from src.tasks import app, delete_expired_activation_tokens
from src.tests.utils import create_activation_token, create_user

TASK_NAME = "src.tasks.delete_expired_activation_tokens"


@pytest.fixture(autouse=True)
def sync_session_to_test_db(monkeypatch, database_url):
    """The task opens sessions with SyncSessionLocal, which points to the real database.
    Point it to the per-worker test database instead (same idea as dependency_overrides)."""
    engine = create_engine(to_sync_url(database_url), poolclass=NullPool)
    monkeypatch.setattr(src.tasks, "SyncSessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    yield
    engine.dispose()


async def remaining_tokens(db_session) -> list[str]:
    stmt = select(ActivationToken.token).execution_options(populate_existing=True)
    return list((await db_session.execute(stmt)).scalars())


async def test_deletes_only_expired_activation_tokens(db_session, caplog):
    expired = [
        await create_activation_token(db_session, await create_user(db_session, email=f"old{i}@example.com"), expired=True)
        for i in range(2)
    ]
    valid = await create_activation_token(db_session, await create_user(db_session, email="new@example.com"))

    with caplog.at_level(logging.INFO):
        deleted = delete_expired_activation_tokens()

    assert deleted == len(expired)
    assert await remaining_tokens(db_session) == [valid.token]
    assert "Deleted 2 expired activation tokens" in caplog.text


async def test_nothing_to_delete_returns_zero(db_session):
    valid = await create_activation_token(db_session, await create_user(db_session))

    assert delete_expired_activation_tokens() == 0
    assert await remaining_tokens(db_session) == [valid.token]


def test_task_runs_through_celery_machinery():
    result = delete_expired_activation_tokens.apply()

    assert result.successful()
    assert result.get() == 0


def test_db_error_fails_the_task(monkeypatch):
    def failing_commit(self) -> None:
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(Session, "commit", failing_commit)

    result = delete_expired_activation_tokens.apply()
    assert result.failed()
    with pytest.raises(OperationalError):
        delete_expired_activation_tokens()


def test_task_is_registered():
    assert TASK_NAME in app.tasks


def test_beat_runs_cleanup_daily_at_midnight_utc():
    schedule = {entry["task"]: entry["schedule"] for entry in app.conf.beat_schedule.values()}

    assert schedule[TASK_NAME] == crontab(minute=0, hour=0)
    assert app.conf.enable_utc is True
