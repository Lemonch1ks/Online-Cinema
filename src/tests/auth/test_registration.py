import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.auth.models import User, UserGroupEnum
from src.auth.security import verify_password
from src.core.config import settings

REGISTER_URL = f"{settings.API_VERSION_PREFIX}/users/register"
VALID_PASSWORD = "StrongPass1!"


async def test_register_creates_inactive_user(client, db_session, email_sender):
    response = await client.post(REGISTER_URL, json={"email": "New.User@Example.com", "password": VALID_PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@example.com"  # email is lowercased
    assert "password" not in body
    assert "hashed_password" not in body

    result = await db_session.execute(
        select(User)
        .where(User.email == "new.user@example.com")
        .options(selectinload(User.group), selectinload(User.activation_token))
    )
    user = result.scalar_one()
    assert user.id == body["id"]
    assert user.is_active is False
    assert user.group.name == UserGroupEnum.USER
    assert user.activation_token is not None
    assert user._hashed_password != VALID_PASSWORD
    assert verify_password(VALID_PASSWORD, user._hashed_password)

    assert len(email_sender.activation_emails) == 1
    recipient, link = email_sender.activation_emails[0]
    assert recipient == "new.user@example.com"
    assert link.endswith(user.activation_token.token)


async def test_register_duplicate_email_returns_409(client, db_session, email_sender):
    payload = {"email": "dup@example.com", "password": VALID_PASSWORD}
    await client.post(REGISTER_URL, json=payload)

    response = await client.post(REGISTER_URL, json={**payload, "email": "DUP@example.com"})

    assert response.status_code == 409
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert len(email_sender.activation_emails) == 1  # no second email


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("Sh0rt!a", id="too-short"),
        pytest.param("nouppercase1!", id="no-uppercase"),
        pytest.param("NOLOWERCASE1!", id="no-lowercase"),
        pytest.param("NoDigitsHere!", id="no-digit"),
        pytest.param("NoSpecial123", id="no-special-char"),
    ],
)
async def test_register_weak_password_returns_422(client, db_session, password):
    response = await client.post(REGISTER_URL, json={"email": "weak@example.com", "password": password})

    assert response.status_code == 422
    assert (await db_session.execute(select(User))).first() is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"email": "not-an-email", "password": VALID_PASSWORD}, id="invalid-email"),
        pytest.param({"password": VALID_PASSWORD}, id="missing-email"),
        pytest.param({"email": "a@example.com"}, id="missing-password"),
    ],
)
async def test_register_invalid_payload_returns_422(client, payload):
    response = await client.post(REGISTER_URL, json=payload)

    assert response.status_code == 422
