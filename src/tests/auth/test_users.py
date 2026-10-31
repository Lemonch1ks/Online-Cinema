import pytest
from sqlalchemy import select

from src.auth.models import RefreshToken
from src.tests.utils import CHANGE_PASSWORD_URL, LOGIN_URL, REFRESH_URL, TEST_EMAIL, TEST_PASSWORD, login

NEW_PASSWORD = "NewStrongPass2!"


# --- POST /change_password ---

async def test_change_password_updates_password_and_revokes_refresh_tokens(
    client, db_session, active_user, auth_tokens, auth_headers
):
    response = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_headers,
    )

    assert response.status_code == 204
    refresh_tokens = (
        await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == active_user.id))
    ).scalars().all()
    assert refresh_tokens == []

    refresh = await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})
    assert refresh.status_code == 401

    old_login = await client.post(LOGIN_URL, data={"username": TEST_EMAIL, "password": TEST_PASSWORD})
    assert old_login.status_code == 401
    await login(client, password=NEW_PASSWORD)


async def test_change_password_with_wrong_old_password_returns_400(client, auth_headers):
    response = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": "WrongPassword1!", "new_password": NEW_PASSWORD},
        headers=auth_headers,
    )

    assert response.status_code == 400
    await login(client)  # old password still works


async def test_change_password_to_same_password_returns_400(client, auth_headers):
    response = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
        headers=auth_headers,
    )

    assert response.status_code == 400


@pytest.mark.parametrize("password", ["short1!", "nouppercase1!", "NOLOWERCASE1!", "NoDigits!!", "NoSpecial123"])
async def test_change_password_with_weak_password_returns_422(client, auth_headers, password):
    response = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": TEST_PASSWORD, "new_password": password},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_change_password_without_auth_returns_401(client, active_user):
    response = await client.post(
        CHANGE_PASSWORD_URL, json={"old_password": TEST_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 401
