import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import RefreshToken, User
from src.auth.security import create_refresh_token, decode_access_token
from src.tests.utils import (
    CHANGE_PASSWORD_URL,
    LOGIN_URL,
    LOGOUT_URL,
    REFRESH_URL,
    TEST_EMAIL,
    TEST_PASSWORD,
    bearer,
    create_user,
)

LOGIN_PAYLOAD = {"username": TEST_EMAIL, "password": TEST_PASSWORD}


# --- /token ---


async def test_login_returns_tokens_and_stores_refresh_token(client, db_session, active_user):
    response = await client.post(LOGIN_URL, data=LOGIN_PAYLOAD)

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert decode_access_token(data["access_token"])["sub"] == TEST_EMAIL
    assert "refresh_token" in data

    stmt = select(RefreshToken).where(RefreshToken.user_id == active_user.id)
    db_token = (await db_session.execute(stmt)).scalar_one()
    assert db_token.token == data["refresh_token"]


async def test_login_with_email_in_other_case_returns_200(client, active_user):
    response = await client.post(LOGIN_URL, data={**LOGIN_PAYLOAD, "username": "TestUser@Example.com"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({**LOGIN_PAYLOAD, "password": f"{TEST_PASSWORD}1"}, id="wrong-password"),
        pytest.param({**LOGIN_PAYLOAD, "username": "unknown@example.com"}, id="unknown-email"),
    ],
)
async def test_login_with_bad_credentials_returns_401(client, active_user, payload):
    response = await client.post(LOGIN_URL, data=payload)

    assert response.status_code == 401


async def test_login_inactive_user_returns_403(client, db_session):
    await create_user(db_session, is_active=False)

    response = await client.post(LOGIN_URL, data=LOGIN_PAYLOAD)

    assert response.status_code == 403


# --- /refresh ---


async def test_refresh_rotates_refresh_token(client, auth_tokens):
    old_payload = {"refresh_token": auth_tokens["refresh_token"]}

    response = await client.post(REFRESH_URL, json=old_payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["refresh_token"] != auth_tokens["refresh_token"]

    response_with_old_token = await client.post(REFRESH_URL, json=old_payload)
    assert response_with_old_token.status_code == 401


async def test_tokens_issued_by_refresh_work(client, auth_tokens):
    new_tokens = (await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})).json()

    assert new_tokens["token_type"] == "bearer"
    protected = await client.post(
        CHANGE_PASSWORD_URL,
        json={"old_password": "WrongPassword1!", "new_password": "NewStrongPass2!"},
        headers=bearer(new_tokens["access_token"]),
    )
    assert protected.status_code == 400  # authenticated (not 401), only the old password is wrong
    second = await client.post(REFRESH_URL, json={"refresh_token": new_tokens["refresh_token"]})
    assert second.status_code == 200


async def test_concurrent_refresh_with_same_token_succeeds_only_once(client, db_session, active_user, auth_tokens):
    payload = {"refresh_token": auth_tokens["refresh_token"]}

    responses = await asyncio.gather(*(client.post(REFRESH_URL, json=payload) for _ in range(2)))

    assert sorted(r.status_code for r in responses) == [200, 401]
    stmt = select(RefreshToken).where(RefreshToken.user_id == active_user.id)
    assert len((await db_session.execute(stmt)).scalars().all()) == 1


async def test_refresh_for_deleted_user_returns_401(client, db_session, active_user, auth_tokens, monkeypatch):
    original_get = AsyncSession.get

    async def user_deleted_meanwhile(self, entity, ident, *args, **kwargs):
        if entity is User:
            return None
        return await original_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", user_deleted_meanwhile)

    response = await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})

    assert response.status_code == 401


@pytest.mark.usefixtures("auth_tokens")
async def test_refresh_with_unknown_token_returns_401(client):
    response = await client.post(REFRESH_URL, json={"refresh_token": "not-a-real-token"})

    assert response.status_code == 401


async def test_refresh_with_expired_token_returns_401(client, db_session, active_user: User):
    expired_token = RefreshToken(
        token=create_refresh_token(),
        user_id=active_user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(expired_token)
    await db_session.commit()

    response = await client.post(REFRESH_URL, json={"refresh_token": expired_token.token})

    assert response.status_code == 401


async def get_refresh_token_from_db(db_session, token: str) -> RefreshToken | None:
    stmt = select(RefreshToken).where(RefreshToken.token == token)
    return (await db_session.execute(stmt)).scalar_one_or_none()


# --- /logout ---


async def test_logout_deletes_refresh_token(client, db_session, auth_tokens, auth_headers):
    payload = {"refresh_token": auth_tokens["refresh_token"]}

    response = await client.post(LOGOUT_URL, json=payload, headers=auth_headers)

    assert response.status_code == 204
    assert await get_refresh_token_from_db(db_session, auth_tokens["refresh_token"]) is None


async def test_logout_twice_with_same_token_returns_401(client, auth_tokens, auth_headers):
    payload = {"refresh_token": auth_tokens["refresh_token"]}
    first_response = await client.post(LOGOUT_URL, json=payload, headers=auth_headers)
    assert first_response.status_code == 204

    response = await client.post(LOGOUT_URL, json=payload, headers=auth_headers)

    assert response.status_code == 401


async def test_logout_without_auth_header_returns_401(client, db_session, auth_tokens):
    payload = {"refresh_token": auth_tokens["refresh_token"]}

    response = await client.post(LOGOUT_URL, json=payload)

    assert response.status_code == 401
    assert await get_refresh_token_from_db(db_session, auth_tokens["refresh_token"]) is not None


async def test_logout_with_other_users_refresh_token_returns_401(client, db_session, auth_headers):
    other_email = "other@example.com"
    await create_user(db_session, email=other_email)
    other_login = await client.post(LOGIN_URL, data={"username": other_email, "password": TEST_PASSWORD})
    other_refresh_token = other_login.json()["refresh_token"]

    response = await client.post(LOGOUT_URL, json={"refresh_token": other_refresh_token}, headers=auth_headers)

    assert response.status_code == 401
    assert await get_refresh_token_from_db(db_session, other_refresh_token) is not None
