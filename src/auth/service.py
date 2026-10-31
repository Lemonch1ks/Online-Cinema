import logging
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User, ActivationToken, PasswordResetToken
from src.auth.security import DUMMY_HASH, verify_password
from src.core.config import settings
from src.notifications.emails import EmailSender, BaseEmailError

logger = logging.getLogger(__name__)


async def get_user(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email).options(joinedload(User.group))
    item = await db.execute(stmt)
    return item.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user(db, email)
    if not user:
        verify_password(password, DUMMY_HASH)
        return None
    if not user.verify_password(password):
        return None
    return user


def validate_token_by_time(token: ActivationToken | PasswordResetToken) -> bool:
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        return False
    return True


async def create_and_send_an_activation_link(act_token: str, email_sender: EmailSender, user: User) -> None:
    activation_link = f"{settings.ACTIVATION_LINK_ENDPOINT}/{act_token}"
    try:
        await email_sender.send_activation_email(user.email, activation_link)
    except BaseEmailError:
        logger.exception("Failed to send activation email to %s", user.email)


async def create_and_send_a_password_reset_link(reset_token: str, email_sender: EmailSender, user: User) -> None:
    reset_link = f"{settings.PASSWORD_RESET_LINK_ENDPOINT}/{reset_token}"
    try:
        await email_sender.send_password_reset_email(user.email, reset_link)
    except BaseEmailError:
        logger.exception("Failed to send password reset email to %s", user.email)
