from datetime import datetime, timedelta, timezone

from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.auth.security import create_refresh_token
from src.auth.models import RefreshToken, User
from src.core.config import settings

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Testpassword1@"
USER_GROUP_ID = 1


async def create_default_user(db: AsyncSession, email, password: str, group_id: int) -> User:
  new_user = User.create(
    email=str(email),
    raw_password=password,
    group_id=group_id,
  )
  db.add(new_user)
  await db.commit()
  return new_user


async def create_activated_user(db: AsyncSession, email, password: str, group_id: int) -> User:
  new_user = User.create(
    email=str(email),
    raw_password=password,
    group_id=group_id,
  )
  db.add(new_user)
  new_user.is_active = True
  await db.commit()
  return new_user


async def test_get_and_store_jwt_token_when_login_is_successful(client, db_session):
  payload = {"username": TEST_EMAIL, "password": TEST_PASSWORD, "group_id": USER_GROUP_ID}
  
  user = await create_activated_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)

  assert response.status_code == 200
  
  data = response.json()
  
  assert "access_token" in data
  assert "refresh_token" in data
  stmt = select(RefreshToken).where(RefreshToken.user_id == user.id).options(joinedload(RefreshToken.user))

  db_token = (await db_session.execute(stmt)).scalar_one_or_none()

  assert db_token.token == response.json()["refresh_token"]


async def test_right_email_wrong_password_return_401(client, db_session):
  payload = {"username": TEST_EMAIL, "password": f"{TEST_PASSWORD}1", "group_id": USER_GROUP_ID}

  await create_activated_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)

  assert response.status_code == 401

async def test_email_not_in_lowercase_return_200(client, db_session):
  payload = {"username": "TestUser@example.com", "password": f"{TEST_PASSWORD}", "group_id": USER_GROUP_ID}

  await create_activated_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)

  assert response.status_code == 200


async def test_inactive_user_token_endpoint_returns_403(client, db_session):
  payload = {"username": TEST_EMAIL, "password": TEST_PASSWORD, "group_id": USER_GROUP_ID}
  await create_default_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)
  assert response.status_code == 403


async def test_unknown_user_token_endpoint_returns_401(client, db_session):
  payload = {"username": TEST_EMAIL, "password": TEST_PASSWORD, "group_id": USER_GROUP_ID}
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)
  assert response.status_code == 401


async def test_refresh_access_token_with_refresh_token(client, db_session):
  payload = {"username": TEST_EMAIL, "password": TEST_PASSWORD, "group_id": USER_GROUP_ID}
  await create_activated_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  first_response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)

  new_payload = {"refresh_token": first_response.json()["refresh_token"]}
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/refresh", json=new_payload)

  assert response.status_code == 200

  data = response.json()

  assert "access_token" in data
  assert "refresh_token" in data

  assert first_response.json()["refresh_token"] != data["refresh_token"]

  response_with_old_token = await client.post(f"{settings.SECURITY_TOKEN_URL}/refresh", json=new_payload)

  assert response_with_old_token.status_code == 401


async def test_refresh_wrong_refresh_token_return_401(client, db_session):
  payload = {"username": TEST_EMAIL, "password": TEST_PASSWORD, "group_id": USER_GROUP_ID}
  await create_activated_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  first_response = await client.post(f"{settings.SECURITY_TOKEN_URL}/token", data=payload)

  assert first_response.status_code == 200

  new_payload = {"refresh_token": "fsafGFSDGSDGW"}
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/refresh", json=new_payload)

  assert response.status_code == 401


async def test_expired_refresh_token_is_not_valid_return_401(client, db_session):
  user = await create_default_user(db=db_session, email=TEST_EMAIL, password=TEST_PASSWORD, group_id=USER_GROUP_ID)
  past_time = datetime.now(timezone.utc) - settings.REFRESH_TOKEN_LIFETIME - timedelta(hours=1)
  refresh_token = create_refresh_token()
  stmt = insert(RefreshToken).values(token=refresh_token, user_id=user.id, expires_at=past_time)
  await db_session.execute(stmt)
  payload = {"refresh_token": refresh_token}
  response = await client.post(f"{settings.SECURITY_TOKEN_URL}/refresh", json=payload)

  assert response.status_code == 401


