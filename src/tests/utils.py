from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import ActivationToken, PasswordResetToken, User
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
