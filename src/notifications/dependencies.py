from functools import lru_cache

from src.core.config import settings
from src.notifications.emails import EmailSender


@lru_cache
def get_email_sender() -> EmailSender:
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
