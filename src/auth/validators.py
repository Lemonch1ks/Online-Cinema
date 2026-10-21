import re

import email_validator

from src.core.config import settings


def validate_password(password):
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must contain at least {settings.PASSWORD_MIN_LENGTH} characters.")
    if not re.search(r'[A-Z]', password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r'[a-z]', password):
        raise ValueError("Password must contain at least one lower letter.")
    if not re.search(r'\d', password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(f"[{re.escape(settings.PASSWORD_SPECIAL_CHARS)}]", password):
        raise ValueError(
            "Password must contain at least one special character: "
            f"{', '.join(settings.PASSWORD_SPECIAL_CHARS)}."
        )
    return password


def validate_email(user_email: str) -> str:
    try:
        email_info = email_validator.validate_email(user_email, check_deliverability=False)
        email = email_info.normalized
    except email_validator.EmailNotValidError as error:
        raise ValueError(str(error))
    else:
        return email
