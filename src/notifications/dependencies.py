from functools import lru_cache

from config.settings import base_app_settings
from src.notifications.emails import EmailSender


@lru_cache
def get_email_sender() -> EmailSender:
    return EmailSender(
        hostname=base_app_settings.EMAIL_HOSTNAME,
        port=base_app_settings.EMAIL_PORT,
        email=base_app_settings.EMAIL_USERNAME,
        password=base_app_settings.EMAIL_PASSWORD,
        use_tls=base_app_settings.EMAIL_USE_TLS,
        template_dir=str(base_app_settings.TEMPLATE_DIR),
        activation_complete_email_template_name=base_app_settings.ACTIVATION_COMPLETE_TEMPLATE_NAME,
        password_complete_email_template_name=base_app_settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
        activation_email_template_name=base_app_settings.ACTIVATION_REQUEST_TEMPLATE_NAME,
        password_email_template_name=base_app_settings.PASSWORD_RESET_REQUEST_TEMPLATE_NAME,
    )
