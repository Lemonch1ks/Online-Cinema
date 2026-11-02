import asyncio
from functools import lru_cache

from src.core.config import settings
from src.notifications.emails import BaseEmailError, EmailSender
from src.tasks import app

EMAIL_METHODS = {
    "activation": "send_activation_email",
    "activation_complete": "send_activation_complete_email",
    "password_reset": "send_password_reset_email",
    "password_reset_complete": "send_password_reset_complete_email",
}


@lru_cache
def get_smtp_sender() -> EmailSender:
    return EmailSender(
        hostname=settings.EMAIL_HOSTNAME,
        port=settings.EMAIL_PORT,
        email=settings.EMAIL_USERNAME,
        password=settings.EMAIL_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        template_dir=str(settings.TEMPLATE_DIR),
        activation_complete_email_template_name=settings.ACTIVATION_COMPLETE_TEMPLATE_NAME,
        password_complete_email_template_name=settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
        activation_email_template_name=settings.ACTIVATION_REQUEST_TEMPLATE_NAME,
        password_email_template_name=settings.PASSWORD_RESET_REQUEST_TEMPLATE_NAME,
        activation_email_subject=settings.ACTIVATION_REQUEST_SUBJECT,
        activation_complete_email_subject=settings.ACTIVATION_COMPLETE_SUBJECT,
        password_email_subject=settings.PASSWORD_RESET_REQUEST_SUBJECT,
        password_complete_email_subject=settings.PASSWORD_RESET_COMPLETE_SUBJECT,
    )


@app.task(autoretry_for=(BaseEmailError,), max_retries=3, retry_backoff=True)
def send_email(kind: str, email: str, link: str) -> None:
    if kind not in EMAIL_METHODS:
        raise ValueError(f"Unknown email kind: {kind}")
    send = getattr(get_smtp_sender(), EMAIL_METHODS[kind])
    asyncio.run(send(email, link))
