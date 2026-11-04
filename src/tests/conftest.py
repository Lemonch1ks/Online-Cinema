import json
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.auth.models import User, UserGroup, UserGroupEnum
from src.core.config import settings
from src.core.database import Base, get_db
from src.main import app
from src.notifications.dependencies import get_email_sender
from src.payments.dependencies import get_payment_gateway
from src.payments.gateway import (
    CheckoutItem,
    CheckoutSession,
    InvalidWebhookError,
    PaymentGatewayError,
    WebhookEvent,
    read_event,
)
from src.storage.dependencies import get_storage
from src.storage.s3 import StorageError
from src.tests.db import alembic, create_database, drop_database, with_database
from src.tests.utils import LOGIN_URL, TEST_EMAIL, TEST_PASSWORD, create_user

TABLES = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)


@pytest.fixture(scope="session")
def database_url(worker_id: str) -> Generator[str]:
    """One database per xdist worker (cinema_test_gw0, ...; cinema_test_master without xdist).

    The schema comes from the real migrations, so every test run also checks that they apply on Postgres.
    """
    base_name = make_url(settings.TEST_DATABASE_URL).database
    url = with_database(settings.TEST_DATABASE_URL, f"{base_name}_{worker_id}")
    create_database(url)
    alembic(url, ("upgrade", "head"))
    yield url
    drop_database(url)


@pytest.fixture(scope="session")
def engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, echo=settings.TEST_DB_ECHO, poolclass=NullPool)


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_database(engine: AsyncEngine) -> None:
    """Empty all tables before each test (not after: a crashed test must not break the next one).

    RESTART IDENTITY resets ids, so the groups get ids 1, 2, 3 again and TEST_USER_GROUP_ID stays valid.
    Groups are re-inserted because some tests delete them.
    """
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await conn.execute(insert(UserGroup), [{"name": group} for group in UserGroupEnum])


@pytest_asyncio.fixture()
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession]:
    async with session_factory() as session:
        yield session


class FakeEmailSender:
    def __init__(self) -> None:
        self.activation_emails: list[tuple[str, str]] = []
        self.activation_complete_emails: list[tuple[str, str]] = []
        self.password_reset_emails: list[tuple[str, str]] = []
        self.password_reset_complete_emails: list[tuple[str, str]] = []
        self.comment_reply_emails: list[tuple[str, str]] = []
        self.comment_like_emails: list[tuple[str, str]] = []
        self.payment_success_emails: list[tuple[str, str]] = []
        self.payment_failed_emails: list[tuple[str, str]] = []
        self.refund_emails: list[tuple[str, str]] = []

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        self.activation_emails.append((email, activation_link))

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        self.activation_complete_emails.append((email, login_link))

    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        self.password_reset_emails.append((email, reset_link))

    async def send_password_reset_complete_email(self, email: str, login_link: str) -> None:
        self.password_reset_complete_emails.append((email, login_link))

    async def send_comment_reply_email(self, email: str, comment_link: str) -> None:
        self.comment_reply_emails.append((email, comment_link))

    async def send_comment_like_email(self, email: str, comment_link: str) -> None:
        self.comment_like_emails.append((email, comment_link))

    async def send_payment_success_email(self, email: str, purchases_link: str) -> None:
        self.payment_success_emails.append((email, purchases_link))

    async def send_payment_failed_email(self, email: str, orders_link: str) -> None:
        self.payment_failed_emails.append((email, orders_link))

    async def send_refund_email(self, email: str, orders_link: str) -> None:
        self.refund_emails.append((email, orders_link))


@pytest.fixture()
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


class FakeStorage:
    """In-memory replacement of S3Storage. Set fail_upload / fail_delete to simulate a storage outage."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.fail_upload = False
        self.fail_delete = False

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail_upload:
            raise StorageError("storage is down")
        self.files[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise StorageError("storage is down")
        self.files.pop(key, None)

    def url(self, key: str) -> str:
        return f"http://storage.test/avatars/{key}"


@pytest.fixture()
def storage() -> FakeStorage:
    return FakeStorage()


class FakePaymentGateway:
    """In-memory replacement of StripeGateway. Set fail to simulate a Stripe outage or rejection.

    Webhook bodies are Stripe event JSON; only FakePaymentGateway.SIGNATURE passes the signature check.
    statuses keeps each payment page status like Stripe does: "open", "complete" or "expired".
    """

    SIGNATURE = "t=1,v1=valid-fake-signature"

    def __init__(self) -> None:
        self.sessions: list[tuple[int, list[CheckoutItem], CheckoutSession]] = []
        self.statuses: dict[str, str] = {}
        self.refunds: list[str] = []
        self.fail = False

    def _check_available(self) -> None:
        if self.fail:
            raise PaymentGatewayError("stripe is down")

    async def create_checkout_session(self, order_id: int, items: list[CheckoutItem]) -> CheckoutSession:
        self._check_available()
        session_id = f"cs_test_fake_{len(self.sessions) + 1}"
        session = CheckoutSession(id=session_id, url=f"https://checkout.stripe.test/c/pay/{session_id}")
        self.sessions.append((order_id, list(items), session))
        self.statuses[session_id] = "open"
        return session

    async def get_checkout_status(self, session_id: str) -> str:
        self._check_available()
        if session_id not in self.statuses:
            raise PaymentGatewayError(f"No such checkout.session: {session_id}")
        return self.statuses[session_id]

    async def close_checkout_session(self, session_id: str) -> str:
        if await self.get_checkout_status(session_id) == "open":
            self.statuses[session_id] = "expired"
        return self.statuses[session_id]

    async def refund(self, payment_intent: str) -> None:
        self._check_available()
        if payment_intent in self.refunds:
            raise PaymentGatewayError(f"Charge for {payment_intent} has already been refunded.")
        self.refunds.append(payment_intent)

    def parse_event(self, payload: bytes, signature: str | None) -> WebhookEvent:
        if signature != self.SIGNATURE:
            raise InvalidWebhookError("No signatures found matching the expected signature for payload")
        try:
            event = json.loads(payload)
            return read_event(event["type"], event["data"]["object"])
        except (ValueError, KeyError, TypeError) as e:
            raise InvalidWebhookError(str(e)) from e


@pytest.fixture()
def payment_gateway() -> FakePaymentGateway:
    return FakePaymentGateway()


@pytest_asyncio.fixture()
async def client(
    email_sender: FakeEmailSender,
    storage: FakeStorage,
    payment_gateway: FakePaymentGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_payment_gateway] = lambda: payment_gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac_client:
        yield ac_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def active_user(db_session: AsyncSession) -> User:
    return await create_user(db_session)


@pytest_asyncio.fixture()
async def auth_tokens(client: AsyncClient, active_user: User) -> dict:
    response = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()


@pytest.fixture()
def auth_headers(auth_tokens: dict) -> dict:
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}
