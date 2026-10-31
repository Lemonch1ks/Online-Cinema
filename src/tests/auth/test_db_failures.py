"""Database errors on commit: endpoints must roll back and answer with an error instead of crashing."""
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import RefreshToken, User, UserGroup, UserGroupEnum
from src.tests.utils import (
    ACTIVATION_RESEND_URL,
    ACTIVATION_URL,
    ADMIN_USERS_URL,
    CHANGE_PASSWORD_URL,
    LOGOUT_URL,
    PASSWORD_RESET_COMPLETE_URL,
    PASSWORD_RESET_REQUEST_URL,
    REFRESH_URL,
    REGISTER_URL,
    TEST_EMAIL,
    TEST_PASSWORD,
    bearer,
    create_activation_token,
    create_password_reset_token,
    create_user,
    create_user_in_group,
    login,
)


@pytest.fixture()
def broken_commit(monkeypatch):
    """Call it after the test data is prepared: from then on every commit fails."""

    def apply() -> None:
        async def failing_commit(self) -> None:
            # OperationalError is a DatabaseError, which is a SQLAlchemyError: matches every except in the code
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

        monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    return apply


@pytest.fixture()
async def inactive_user(db_session) -> User:
    return await create_user(db_session, is_active=False)


async def test_register_returns_500_on_db_error(client, db_session, broken_commit):
    broken_commit()

    response = await client.post(REGISTER_URL, json={"email": "new@example.com", "password": "StrongPass1!"})

    assert response.status_code == 500
    assert (await db_session.execute(select(User))).scalars().all() == []


async def test_register_returns_500_without_default_group(client, db_session):
    await db_session.execute(delete(UserGroup).where(UserGroup.name == UserGroupEnum.USER))
    await db_session.commit()

    response = await client.post(REGISTER_URL, json={"email": "new@example.com", "password": "StrongPass1!"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Default user group not found."


async def test_activate_returns_500_on_db_error(client, db_session, inactive_user, broken_commit):
    token = await create_activation_token(db_session, inactive_user)
    broken_commit()

    response = await client.get(f"{ACTIVATION_URL}{token.token}")

    assert response.status_code == 500
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is False


async def test_resend_returns_500_on_db_error(client, email_sender, inactive_user, broken_commit):
    broken_commit()

    response = await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 500
    assert email_sender.activation_emails == []  # no link to a token that was never saved


async def test_reset_request_returns_500_on_db_error(client, email_sender, active_user, broken_commit):
    broken_commit()

    response = await client.post(PASSWORD_RESET_REQUEST_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 500
    assert email_sender.password_reset_emails == []


async def test_reset_complete_returns_500_on_db_error(client, db_session, active_user, broken_commit, monkeypatch):
    token = await create_password_reset_token(db_session, active_user)
    broken_commit()

    response = await client.post(
        PASSWORD_RESET_COMPLETE_URL, json={"token": token.token, "new_password": "NewStrongPass2!"}
    )

    assert response.status_code == 500
    monkeypatch.undo()
    await login(client)  # old password still works


async def test_change_password_returns_500_on_db_error(client, auth_headers, broken_commit, monkeypatch):
    broken_commit()

    response = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": TEST_PASSWORD, "new_password": "NewStrongPass2!"},
        headers=auth_headers,
    )

    assert response.status_code == 500
    monkeypatch.undo()
    await login(client)


async def test_refresh_returns_400_on_db_error(client, db_session, auth_tokens, broken_commit):
    broken_commit()

    response = await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})

    assert response.status_code == 400
    # the old refresh token was not deleted
    stmt = select(RefreshToken).where(RefreshToken.token == auth_tokens["refresh_token"])
    assert (await db_session.execute(stmt)).scalar_one_or_none() is not None


async def test_logout_returns_400_on_db_error(client, auth_tokens, auth_headers, broken_commit):
    broken_commit()

    response = await client.post(
        LOGOUT_URL, json={"refresh_token": auth_tokens["refresh_token"]}, headers=auth_headers
    )

    assert response.status_code == 400


@pytest.fixture()
async def admin_headers(client, db_session) -> dict:
    await create_user_in_group(db_session, "admin@example.com", UserGroupEnum.ADMIN)
    return bearer((await login(client, "admin@example.com"))["access_token"])


async def test_admin_change_group_returns_500_on_db_error(client, active_user, admin_headers, broken_commit):
    broken_commit()

    response = await client.patch(
        f"{ADMIN_USERS_URL}/{active_user.id}/group",
        json={"new_group_rank": UserGroupEnum.ADMIN},
        headers=admin_headers,
    )

    assert response.status_code == 500


async def test_admin_activate_returns_500_on_db_error(client, db_session, inactive_user, admin_headers, broken_commit):
    broken_commit()

    response = await client.post(f"{ADMIN_USERS_URL}/{inactive_user.id}/activate", headers=admin_headers)

    assert response.status_code == 500
    await db_session.refresh(inactive_user)
    assert inactive_user.is_active is False
