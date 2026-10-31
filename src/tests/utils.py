from datetime import datetime, timedelta, timezone

from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import ActivationToken, PasswordResetToken, User, UserGroup, UserGroupEnum
from src.auth.security import generate_token
from src.core.config import settings


TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Testpassword1@"
TEST_USER_GROUP_ID = 1

LOGIN_URL = f"{settings.SECURITY_TOKEN_URL}/token"
REFRESH_URL = f"{settings.SECURITY_TOKEN_URL}/refresh"
LOGOUT_URL = f"{settings.SECURITY_TOKEN_URL}/logout"

ACTIVATION_URL = f"{settings.ACTIVATION_LINK_BASE}/"
ACTIVATION_RESEND_URL = f"{settings.ACTIVATION_LINK_BASE}/resend"
PASSWORD_RESET_URL = f"{settings.PASSWORD_RESET_LINK_BASE}/"
PASSWORD_RESET_REQUEST_URL = f"{settings.PASSWORD_RESET_LINK_BASE}/request"
PASSWORD_RESET_COMPLETE_URL = f"{settings.PASSWORD_RESET_LINK_BASE}/complete"

REGISTER_URL = f"{settings.API_VERSION_PREFIX}/users/register"
CHANGE_PASSWORD_URL = f"{settings.API_VERSION_PREFIX}/users/change_password"
ADMIN_USERS_URL = f"{settings.API_VERSION_PREFIX}/admins/users"

MOVIES_URL = f"{settings.API_VERSION_PREFIX}/movies"
GENRES_URL = f"{settings.API_VERSION_PREFIX}/genres"


async def create_user(
    db: AsyncSession,
    email: str = TEST_EMAIL,
    password: str = TEST_PASSWORD,
    group_id: int = TEST_USER_GROUP_ID,
    is_active: bool = True,
) -> User:
    user = User.create(email=email, raw_password=password, group_id=group_id)
    user.is_active = is_active
    db.add(user)
    await db.commit()
    return user


async def get_group_id(db: AsyncSession, group: UserGroupEnum) -> int:
    # group ids come from insert order, not from enum values (ADMIN has id 3, rank 10)
    return (await db.execute(select(UserGroup.id).where(UserGroup.name == group))).scalar_one()


async def create_user_in_group(db: AsyncSession, email: str, group: UserGroupEnum, is_active: bool = True) -> User:
    return await create_user(db, email=email, group_id=await get_group_id(db, group), is_active=is_active)


async def login(client: AsyncClient, email: str = TEST_EMAIL, password: str = TEST_PASSWORD) -> dict:
    response = await client.post(LOGIN_URL, data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _expires_at(lifetime: timedelta, expired: bool) -> datetime:
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=1) if expired else now + lifetime


async def create_activation_token(db: AsyncSession, user: User, expired: bool = False) -> ActivationToken:
    token = ActivationToken(
        user_id=user.id,
        token=generate_token(settings.ACTIVATION_TOKEN_NBYTES),
        expires_at=_expires_at(settings.ACTIVATION_TOKEN_LIFETIME, expired),
    )
    db.add(token)
    await db.commit()
    return token


async def create_password_reset_token(db: AsyncSession, user: User, expired: bool = False) -> PasswordResetToken:
    token = PasswordResetToken(
        user_id=user.id,
        token=generate_token(settings.PASSWORD_RESET_TOKEN_NBYTES),
        expires_at=_expires_at(settings.PASSWORD_RESET_TOKEN_LIFETIME, expired),
    )
    db.add(token)
    await db.commit()
    return token
