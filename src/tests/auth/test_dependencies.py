from datetime import timedelta

import jwt
import pytest
from sqlalchemy import update

from src.auth.models import User
from src.auth.security import create_access_token
from src.core.config import settings
from src.tests.utils import CHANGE_PASSWORD_URL, REFRESH_URL, TEST_EMAIL, TEST_PASSWORD, bearer

# change_password is a simple endpoint behind get_current_active_user
PAYLOAD = {"old_password": TEST_PASSWORD, "new_password": "NewStrongPass2!"}


async def call_protected(client, token: str):
    return await client.post(CHANGE_PASSWORD_URL, json=PAYLOAD, headers=bearer(token))


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode({"sub": TEST_EMAIL}, "wrong-secret-key-wrong-secret-key", algorithm=settings.ALGORITHM),
        create_access_token({"sub": TEST_EMAIL}, expires_delta=timedelta(seconds=-1)),
        create_access_token({"user": TEST_EMAIL}),  # no "sub" claim
    ],
    ids=["garbage", "wrong-signature", "expired", "no-sub"],
)
async def test_invalid_access_token_returns_401(client, active_user, token):
    response = await call_protected(client, token)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_token_of_unknown_user_returns_401(client):
    response = await call_protected(client, create_access_token({"sub": "ghost@example.com"}))

    assert response.status_code == 401


async def test_token_of_deactivated_user_returns_403(client, db_session, active_user, auth_tokens):
    await db_session.execute(update(User).where(User.id == active_user.id).values(is_active=False))
    await db_session.commit()

    response = await call_protected(client, auth_tokens["access_token"])
    refresh = await client.post(REFRESH_URL, json={"refresh_token": auth_tokens["refresh_token"]})

    assert response.status_code == 403
    assert refresh.status_code == 403
