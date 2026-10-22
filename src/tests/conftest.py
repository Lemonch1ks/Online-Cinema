from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx2 import AsyncClient, ASGITransport
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.auth.models import UserGroup, UserGroupEnum
from src.core.config import settings
from src.core.database import Base, enable_sqlite_foreign_keys, get_db
from src.main import app
from src.notifications.dependencies import get_email_sender


# StaticPool: in-memory SQLite lives per connection, so all sessions must share one.
engine = create_async_engine(
    settings.TEST_DATABASE_URL,
    echo=settings.TEST_DB_ECHO,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
enable_sqlite_foreign_keys(engine)

TestSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def prepare_database() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

        await conn.execute(insert(UserGroup), [{"name": group} for group in UserGroupEnum])
    yield


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


class FakeEmailSender:

    def __init__(self) -> None:
        self.activation_emails: list[tuple[str, str]] = []

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        self.activation_emails.append((email, activation_link))


@pytest.fixture()
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest_asyncio.fixture()
async def client(email_sender: FakeEmailSender) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac_client:
        yield ac_client
    app.dependency_overrides.clear()
