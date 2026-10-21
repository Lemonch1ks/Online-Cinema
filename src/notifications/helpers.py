import logging
from datetime import datetime, timezone


from config.settings import base_app_settings

from src.db.models import User
from src.notifications.emails import EmailSender, BaseEmailError
from src.db.models import ActivationToken, PasswordResetToken

logger = logging.getLogger(__name__)

def validate_token_by_time(token: ActivationToken | PasswordResetToken) -> bool:
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        return False
    return True


async def create_and_send_an_activation_link(act_token:str, email_sender: EmailSender, user: User) -> None:
    activation_link = f"{base_app_settings.ACTIVATION_LINK_ENDPOINT}/{act_token}"
    try:
        await email_sender.send_activation_email(user.email, activation_link)
    except BaseEmailError:
        logger.exception("Failed to send activation email to %s", user.email)


async def create_and_send_a_password_reset_link(reset_token:str, email_sender: EmailSender, user: User) -> None:
    reset_link = f"{base_app_settings.PASSWORD_RESET_LINK_ENDPOINT}/{reset_token}"
    try:
        await email_sender.send_password_reset_email(user.email, reset_link)
    except BaseEmailError:
        logger.exception("Failed to send password reset email to %s", user.email)
