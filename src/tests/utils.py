from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.core.config import settings


TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Testpassword1@"
TEST_USER_GROUP_ID = 1

LOGIN_URL = f"{settings.SECURITY_TOKEN_URL}/token"
REFRESH_URL = f"{settings.SECURITY_TOKEN_URL}/refresh"
LOGOUT_URL = f"{settings.SECURITY_TOKEN_URL}/logout"



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
