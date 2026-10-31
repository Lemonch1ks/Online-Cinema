import pytest
from sqlalchemy import select

from src.auth.models import ActivationToken, PasswordResetToken, RefreshToken, User
from src.tests.utils import (
    ACTIVATION_RESEND_URL,
    ACTIVATION_URL,
    LOGIN_URL,
    PASSWORD_RESET_COMPLETE_URL,
    PASSWORD_RESET_REQUEST_URL,
    PASSWORD_RESET_URL,
    REFRESH_URL,
    TEST_EMAIL,
    TEST_PASSWORD,
    create_activation_token,
    create_password_reset_token,
    create_user,
)

NEW_PASSWORD = "NewStrongPass2!"
UNKNOWN_EMAIL = "nobody@example.com"


@pytest.fixture()
async def inactive_user(db_session) -> User:
    return await create_user(db_session, is_active=False)


async def get_activation_token(db_session, user_id: int) -> ActivationToken | None:
    stmt = select(ActivationToken).where(ActivationToken.user_id == user_id).execution_options(populate_existing=True)
    return (await db_session.execute(stmt)).scalar_one_or_none()


async def get_password_reset_token(db_session, user_id: int) -> PasswordResetToken | None:
    stmt = (
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    return (await db_session.execute(stmt)).scalar_one_or_none()


# --- GET /activate/{token} ---

async def test_activate_with_valid_token_activates_user(client, db_session, email_sender, inactive_user):
    token = await create_activation_token(db_session, inactive_user)

    response = await client.get(f"{ACTIVATION_URL}{token.token}")

    assert response.status_code == 200
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is True
    assert await get_activation_token(db_session, inactive_user.id) is None
    assert [email for email, _ in email_sender.activation_complete_emails] == [TEST_EMAIL]


async def test_activate_with_unknown_token_returns_400(client, inactive_user):
    response = await client.get(f"{ACTIVATION_URL}unknown-token")

    assert response.status_code == 400


async def test_activate_with_expired_token_returns_400(client, db_session, email_sender, inactive_user):
    token = await create_activation_token(db_session, inactive_user, expired=True)

    response = await client.get(f"{ACTIVATION_URL}{token.token}")

    assert response.status_code == 400
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is False
    assert email_sender.activation_complete_emails == []


async def test_activated_user_can_log_in(client, db_session, inactive_user):
    token = await create_activation_token(db_session, inactive_user)
    await client.get(f"{ACTIVATION_URL}{token.token}")

    response = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": TEST_PASSWORD})

    assert response.status_code == 200


# --- POST /activate/resend ---

async def test_resend_replaces_existing_activation_token(client, db_session, email_sender, inactive_user):
    old_token = await create_activation_token(db_session, inactive_user, expired=True)
    old_value = old_token.token

    response = await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    new_token = await get_activation_token(db_session, inactive_user.id)
    assert new_token is not None
    assert new_token.token != old_value

    assert len(email_sender.activation_emails) == 1
    recipient, link = email_sender.activation_emails[0]
    assert recipient == TEST_EMAIL
    assert link.endswith(new_token.token)


async def test_resend_creates_token_when_user_has_none(client, db_session, email_sender, inactive_user):
    response = await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    token = await get_activation_token(db_session, inactive_user.id)
    assert token is not None
    assert len(email_sender.activation_emails) == 1


async def test_resent_link_activates_account(client, db_session, email_sender, inactive_user):
    await create_activation_token(db_session, inactive_user, expired=True)
    await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})
    _, link = email_sender.activation_emails[0]
    token = link.rsplit("/", 1)[-1]

    response = await client.get(f"{ACTIVATION_URL}{token}")

    assert response.status_code == 200
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is True


async def test_resend_response_is_same_for_all_emails(client, db_session, email_sender, active_user):
    await create_user(db_session, email="inactive@example.com", is_active=False)

    responses = [
        await client.post(ACTIVATION_RESEND_URL, json={"email": email})
        for email in (UNKNOWN_EMAIL, TEST_EMAIL, "inactive@example.com")
    ]

    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["detail"] for r in responses}) == 1  # no user enumeration
    # only the inactive account gets a new link
    assert [email for email, _ in email_sender.activation_emails] == ["inactive@example.com"]


@pytest.mark.parametrize("payload", [{}, {"email": "not-an-email"}])
async def test_resend_invalid_payload_returns_422(client, payload):
    response = await client.post(ACTIVATION_RESEND_URL, json=payload)

    assert response.status_code == 422


# --- POST /password_reset/request ---

async def test_reset_request_creates_token_and_sends_email(client, db_session, email_sender, active_user):
    response = await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    token = await get_password_reset_token(db_session, active_user.id)
    assert token is not None

    assert len(email_sender.password_reset_emails) == 1
    recipient, link = email_sender.password_reset_emails[0]
    assert recipient == TEST_EMAIL
    assert link.endswith(token.token)


async def test_reset_request_replaces_existing_token(client, db_session, email_sender, active_user):
    old_token = await create_password_reset_token(db_session, active_user)
    old_value = old_token.token

    response = await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    new_token = await get_password_reset_token(db_session, active_user.id)
    assert new_token.token != old_value
    assert email_sender.password_reset_emails[0][1].endswith(new_token.token)


async def test_reset_request_response_is_same_for_all_emails(client, db_session, email_sender, active_user):
    await create_user(db_session, email="inactive@example.com", is_active=False)

    responses = [
        await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": email})
        for email in (UNKNOWN_EMAIL, "inactive@example.com", TEST_EMAIL)
    ]

    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["detail"] for r in responses}) == 1  # no user enumeration
    # only the active account gets a reset link
    assert [email for email, _ in email_sender.password_reset_emails] == [TEST_EMAIL]


# --- GET /password_reset/{token} ---

async def test_check_reset_token_valid_does_not_consume_it(client, db_session, active_user):
    token = await create_password_reset_token(db_session, active_user)

    response = await client.get(f"{PASSWORD_RESET_URL}{token.token}")

    assert response.status_code == 200
    assert await get_password_reset_token(db_session, active_user.id) is not None


async def test_check_reset_token_unknown_returns_400(client):
    response = await client.get(f"{PASSWORD_RESET_URL}unknown-token")

    assert response.status_code == 400


async def test_check_reset_token_expired_returns_400(client, db_session, active_user):
    token = await create_password_reset_token(db_session, active_user, expired=True)

    response = await client.get(f"{PASSWORD_RESET_URL}{token.token}")

    assert response.status_code == 400


# --- POST /password_reset/complete ---

async def test_complete_reset_changes_password_and_revokes_tokens(
    client, db_session, email_sender, active_user, auth_tokens
):
    token = await create_password_reset_token(db_session, active_user)

    response = await client.post(
        PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    assert await get_password_reset_token(db_session, active_user.id) is None
    refresh_tokens = (
        await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == active_user.id))
    ).scalars().all()
    assert refresh_tokens == []
    assert [email for email, _ in email_sender.password_reset_complete_emails] == [TEST_EMAIL]

    old_login = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": TEST_PASSWORD})
    new_login = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": NEW_PASSWORD})
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_complete_reset_old_refresh_token_no_longer_works(client, db_session, active_user, auth_tokens):
    token = await create_password_reset_token(db_session, active_user)
    await client.post(PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": NEW_PASSWORD})

    response = await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})

    assert response.status_code == 401


async def test_complete_reset_with_unknown_token_returns_400(client, active_user):
    response = await client.post(
        PASSWORD_RESET_COMPLETE_URL, json={"token": "unknown-token", "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400


async def test_complete_reset_with_expired_token_keeps_old_password(client, db_session, active_user):
    token = await create_password_reset_token(db_session, active_user, expired=True)

    response = await client.post(
        PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400
    login = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200


@pytest.mark.parametrize("password", ["short1!", "nouppercase1!", "NoDigits!!", "NoSpecial123"])
async def test_complete_reset_with_weak_password_returns_422(client, db_session, active_user, password):
    token = await create_password_reset_token(db_session, active_user)

    response = await client.post(PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": password})

    assert response.status_code == 422
    assert await get_password_reset_token(db_session, active_user.id) is not None  # token not consumed


# --- end-to-end ---

async def test_forgot_password_full_flow(client, email_sender, active_user):
    await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": TEST_EMAIL})
    _, link = email_sender.password_reset_emails[0]
    token = link.rsplit("/", 1)[-1]

    check = await client.get(f"{PASSWORD_RESET_URL}{token}")
    complete = await client.post(PASSWORD_RESET_COMPLETE_URL, json={"token": token, "new_password": NEW_PASSWORD})
    login = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": NEW_PASSWORD})

    assert check.status_code == 200
    assert complete.status_code == 200
    assert login.status_code == 200
