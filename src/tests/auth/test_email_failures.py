"""If the SMTP server is down, endpoints must still succeed: the email error is only logged."""
import logging

import pytest
from sqlalchemy import select

from src.auth.models import User, UserGroupEnum
from src.notifications.emails import BaseEmailError
from src.tests.utils import (
    ACTIVATION_RESEND_URL,
    ACTIVATION_URL,
    ADMIN_USERS_URL,
    PASSWORD_RESET_COMPLETE_URL,
    PASSWORD_RESET_REQUEST_URL,
    REGISTER_URL,
    TEST_EMAIL,
    bearer,
    create_activation_token,
    create_password_reset_token,
    create_user,
    create_user_in_group,
    login,
)


class FailingEmailSender:
    def __init__(self) -> None:
        self.attempts = 0

    async def _fail(self, *args) -> None:
        self.attempts += 1
        raise BaseEmailError("SMTP server is down")

    send_activation_email = _fail
    send_activation_complete_email = _fail
    send_password_reset_email = _fail
    send_password_reset_complete_email = _fail


@pytest.fixture()
def email_sender() -> FailingEmailSender:
    # overrides the conftest fixture, so the `client` fixture injects this sender
    return FailingEmailSender()


@pytest.fixture()
async def inactive_user(db_session) -> User:
    return await create_user(db_session, is_active=False)


async def test_register_succeeds_when_email_fails(client, db_session, email_sender, caplog):
    with caplog.at_level(logging.ERROR):
        response = await client.post(REGISTER_URL, json={"email": "new@example.com", "password": "StrongPass1!"})

    assert response.status_code == 201
    assert (await db_session.execute(select(User).where(User.email == "new@example.com"))).scalar_one()
    assert email_sender.attempts == 1
    assert "Failed to send activation email" in caplog.text


async def test_resend_activation_succeeds_when_email_fails(client, email_sender, inactive_user):
    response = await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    assert email_sender.attempts == 1


async def test_activate_succeeds_when_email_fails(client, db_session, email_sender, inactive_user):
    token = await create_activation_token(db_session, inactive_user)

    response = await client.get(f"{ACTIVATION_URL}{token.token}")

    assert response.status_code == 200
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is True
    assert email_sender.attempts == 1


async def test_reset_request_succeeds_when_email_fails(client, email_sender, active_user, caplog):
    with caplog.at_level(logging.ERROR):
        response = await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    assert email_sender.attempts == 1
    assert "Failed to send password reset email" in caplog.text


async def test_reset_complete_succeeds_when_email_fails(client, db_session, email_sender, active_user):
    token = await create_password_reset_token(db_session, active_user)

    response = await client.post(
        PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": "NewStrongPass2!"}
    )

    assert response.status_code == 200
    assert email_sender.attempts == 1
    await login(client, password="NewStrongPass2!")


async def test_admin_activate_succeeds_when_email_fails(client, db_session, email_sender, inactive_user):
    await create_user_in_group(db_session, "admin@example.com", UserGroupEnum.ADMIN)
    headers = bearer((await login(client, "admin@example.com"))["access_token"])

    response = await client.post(f"{ADMIN_USERS_URL}/{inactive_user.id}/activate", headers=headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert email_sender.attempts == 1
