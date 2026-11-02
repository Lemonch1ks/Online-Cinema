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
        ("mysql+pymysql://user:pass@db/cinema", "mysql+pymysql://user:pass@db/cinema"),
    ],
)
def test_sync_database_url(async_url, sync_url):
    assert settings.model_copy(update={"DATABASE_URL": async_url}).SYNC_DATABASE_URL == sync_url


REQUIRED_SETTINGS = {
    "SECRET_KEY": "x",
    "EMAIL_HOSTNAME": "localhost",
    "EMAIL_PORT": 1025,
    "EMAIL_USERNAME": "noreply@example.com",
    "EMAIL_PASSWORD": "",
    "EMAIL_USE_TLS": False,
    "S3_ACCESS_KEY": "key",
    "S3_SECRET_KEY": "secret",
}


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{"DATABASE_URL": "postgresql+asyncpg://u:p@db/cinema", **REQUIRED_SETTINGS, **overrides})


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **REQUIRED_SETTINGS)

    assert [e["loc"] for e in error.value.errors()] == [("DATABASE_URL",)]


def test_derived_urls_follow_api_prefix_and_base_url():
    custom = make_settings(API_VERSION_PREFIX="/api/v2", APP_BASE_URL="https://cinema.example")

    assert custom.SECURITY_TOKEN_URL == "/api/v2/security"
    assert custom.ACTIVATION_LINK_BASE == "/api/v2/accounts/activate"
    assert custom.PASSWORD_RESET_LINK_BASE == "/api/v2/accounts/password_reset"
    assert custom.ACTIVATION_LINK_ENDPOINT == "https://cinema.example/api/v2/accounts/activate"
    assert custom.PASSWORD_RESET_LINK_ENDPOINT == "https://cinema.example/api/v2/accounts/password_reset"


# --- database ---

async def test_get_db_yields_session_and_closes_it():
    generator = database.get_db()
    session = await anext(generator)

    assert isinstance(session, AsyncSession)
    await generator.aclose()


async def test_deleting_user_cascades_to_tokens(db_session, active_user, auth_tokens):
    await create_activation_token(db_session, active_user)

    await db_session.execute(delete(User).where(User.id == active_user.id))
    await db_session.commit()

    for model in (ActivationToken, RefreshToken):
        assert (await db_session.execute(select(func.count()).select_from(model))).scalar() == 0


async def test_foreign_keys_are_enforced(db_session):
    db_session.add(RefreshToken(token="orphan", user_id=9999))

    with pytest.raises(IntegrityError):
        await db_session.commit()
