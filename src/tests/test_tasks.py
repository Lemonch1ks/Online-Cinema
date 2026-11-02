"""Celery tasks: called directly, no Redis or worker needed."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from celery.schedules import crontab
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import src.tasks
from src.auth.models import ActivationToken, User, UserProfile
from src.core.config import to_sync_url
from src.storage.s3 import StorageError
from src.tasks import app, delete_expired_activation_tokens, delete_orphan_avatars
from src.tests.utils import create_activation_token, create_user

TASK_NAME = "src.tasks.delete_expired_activation_tokens"
ORPHANS_TASK_NAME = "src.tasks.delete_orphan_avatars"


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
        await create_activation_token(
            db_session, await create_user(db_session, email=f"old{i}@example.com"), expired=True
        )
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


class ListingStorage:
    """Storage fake for the cleanup task: objects with their upload time."""

    def __init__(self, objects: dict[str, datetime], fail: bool = False) -> None:
        self.objects = dict(objects)
        self.fail = fail
        self.deleted: list[str] = []

    async def list_objects(self) -> list[tuple[str, datetime]]:
        if self.fail:
            raise StorageError("storage is down")
        return list(self.objects.items())

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key)


def test_cleanup_deletes_only_old_unreferenced_avatars(monkeypatch, caplog):
    with src.tasks.SyncSessionLocal() as session:
        user = User.create(email="owner@example.com", raw_password="StrongPass1!", group_id=1)
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, avatar=f"{user.id}/kept.png"))
        session.commit()
        user_id = user.id
    old = datetime.now(UTC) - timedelta(days=2)
    storage = ListingStorage(
        {
            f"{user_id}/kept.png": old,
            f"{user_id}/orphan.png": old,
            f"{user_id}/just-uploaded.png": datetime.now(UTC),
        }
    )
    monkeypatch.setattr(src.tasks, "get_storage", lambda: storage)

    with caplog.at_level(logging.INFO):
        deleted = delete_orphan_avatars()

    assert deleted == 1
    assert storage.deleted == [f"{user_id}/orphan.png"]
    assert "Deleted 1 orphan avatars" in caplog.text


def test_cleanup_with_empty_bucket_returns_zero(monkeypatch):
    storage = ListingStorage({})
    monkeypatch.setattr(src.tasks, "get_storage", lambda: storage)

    assert delete_orphan_avatars() == 0


def test_cleanup_fails_the_task_when_storage_is_down(monkeypatch):
    monkeypatch.setattr(src.tasks, "get_storage", lambda: ListingStorage({}, fail=True))

    assert delete_orphan_avatars.apply().failed()


def test_beat_runs_orphan_cleanup_daily_after_token_cleanup():
    schedule = {entry["task"]: entry["schedule"] for entry in app.conf.beat_schedule.values()}

    assert schedule[ORPHANS_TASK_NAME] == crontab(minute=30, hour=0)
