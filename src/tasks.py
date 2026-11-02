from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger
from sqlalchemy import delete

from src.auth.models import ActivationToken
from src.core.config import settings
from src.core.database import SyncSessionLocal


logger = get_task_logger(__name__)

app = Celery('tasks', broker=settings.BROKER_URL)


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs) -> None:
    sender.add_periodic_task(
        crontab(minute=0, hour=0),
        delete_expired_activation_tokens.s(),
    )


@app.task
def delete_expired_activation_tokens() -> int:
    stmt = delete(ActivationToken).where(ActivationToken.expires_at < datetime.now(timezone.utc))

    with SyncSessionLocal() as session:
        result = session.execute(stmt)
        session.commit()

    logger.info("Deleted %d expired activation tokens", result.rowcount)
    return result.rowcount
