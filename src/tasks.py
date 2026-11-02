import asyncio
from datetime import UTC, datetime

from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger
from sqlalchemy import delete, select

from src.auth.models import ActivationToken, UserProfile
from src.core.config import settings
from src.core.database import SyncSessionLocal
from src.storage.dependencies import get_storage

logger = get_task_logger(__name__)

app = Celery("tasks", broker=settings.BROKER_URL, include=["src.notifications.tasks"])


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs) -> None:
    sender.add_periodic_task(
        crontab(minute=0, hour=0),
        delete_expired_activation_tokens.s(),
    )
    sender.add_periodic_task(
        crontab(minute=30, hour=0),
        delete_orphan_avatars.s(),
    )


@app.task
def delete_expired_activation_tokens() -> int:
    stmt = delete(ActivationToken).where(ActivationToken.expires_at < datetime.now(UTC))

    with SyncSessionLocal() as session:
        result = session.execute(stmt)
        session.commit()

    logger.info("Deleted %d expired activation tokens", result.rowcount)
    return result.rowcount


@app.task
def delete_orphan_avatars() -> int:
    storage = get_storage()
    uploaded_before = datetime.now(UTC) - settings.ORPHAN_AVATAR_MIN_AGE

    with SyncSessionLocal() as session:
        referenced = set(session.scalars(select(UserProfile.avatar).where(UserProfile.avatar.is_not(None))))

    async def delete_orphans() -> int:
        orphans = [
            key
            for key, uploaded_at in await storage.list_objects()
            if key not in referenced and uploaded_at < uploaded_before
        ]
        for key in orphans:
            await storage.delete(key)
        return len(orphans)

    deleted = asyncio.run(delete_orphans())
    logger.info("Deleted %d orphan avatars", deleted)
    return deleted
