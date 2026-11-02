import re
from datetime import date
from io import BytesIO

import email_validator
from PIL import Image, UnidentifiedImageError

from src.core.config import settings

NAME_PATTERN = re.compile(r"[^\W\d_]+(?:[ '-][^\W\d_]+)*")
MIN_BIRTH_YEAR = 1900


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


def validate_name(name: str) -> str:
    name = name.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Name may contain only letters, single spaces, hyphens and apostrophes.")
    return name


def validate_birth_date(birth_date: date) -> date:
    if birth_date.year < MIN_BIRTH_YEAR:
        raise ValueError(f"Birth year must be {MIN_BIRTH_YEAR} or later.")
    if birth_date > date.today():
        raise ValueError("Birth date cannot be in the future.")
    return birth_date


def validate_avatar(data: bytes) -> str:
    """Check size and the real image format (from the content, not from the client's filename or Content-Type).

    Returns the Pillow format name, e.g. "PNG".
    """
    if len(data) > settings.AVATAR_MAX_SIZE:
        raise ValueError(f"Avatar must not be larger than {settings.AVATAR_MAX_SIZE // 1024} KB.")
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError("Avatar is not a valid image.") from error
    if image_format not in settings.AVATAR_FORMATS:
        raise ValueError(f"Unsupported avatar format {image_format}, use one of: {', '.join(settings.AVATAR_FORMATS)}.")
    return image_format
