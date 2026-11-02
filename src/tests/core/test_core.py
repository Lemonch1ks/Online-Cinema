import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import ActivationToken, RefreshToken, User
from src.core import database
from src.core.config import Settings, settings
from src.tests.utils import create_activation_token


# --- config ---

@pytest.mark.parametrize(
    ("async_url", "sync_url"),
    [
        ("postgresql+asyncpg://user:pass@db:5432/cinema", "postgresql+psycopg://user:pass@db:5432/cinema"),
        ("mysql+pymysql://user:pass@db/cinema", "mysql+pymysql://user:pass@db/cinema"),  # unknown driver kept as is
    ],
)
def test_sync_database_url(async_url, sync_url):
    # Alembic runs synchronously, so it needs a sync driver; the password must survive the conversion
    assert settings.model_copy(update={"DATABASE_URL": async_url}).SYNC_DATABASE_URL == sync_url


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    required = {
        "SECRET_KEY": "x",
        "EMAIL_HOSTNAME": "localhost",
        "EMAIL_PORT": 1025,
        "EMAIL_USERNAME": "noreply@example.com",
        "EMAIL_PASSWORD": "",
        "EMAIL_USE_TLS": False,
    }

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **required)

    assert [e["loc"] for e in error.value.errors()] == [("DATABASE_URL",)]


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


async def test_deleting_user_cascades_to_tokens(db_session, active_user, auth_tokens):
    # ON DELETE CASCADE is done by Postgres itself: a Core DELETE bypasses the ORM relationship cascades
    await create_activation_token(db_session, active_user)

    await db_session.execute(delete(User).where(User.id == active_user.id))
    await db_session.commit()

    for model in (ActivationToken, RefreshToken):
        assert (await db_session.execute(select(func.count()).select_from(model))).scalar() == 0


async def test_foreign_keys_are_enforced(db_session):
    db_session.add(RefreshToken(token="orphan", user_id=9999))

    with pytest.raises(IntegrityError):
        await db_session.commit()
