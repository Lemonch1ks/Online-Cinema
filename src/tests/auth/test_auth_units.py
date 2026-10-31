"""Unit tests: no HTTP, no database."""
from datetime import datetime, timedelta, timezone

import pytest

from src.auth.models import ActivationToken, RefreshToken, User, UserGroup, UserGroupEnum
from src.auth.security import create_access_token, decode_access_token
from src.auth.service import validate_token_by_time
from src.auth.validators import validate_email, validate_password
from src.core.config import settings


# --- validators ---

@pytest.mark.parametrize("password", ["Valid1!pass", "Another$Pass9"])
def test_validate_password_accepts_strong_password(password):
    assert validate_password(password) == password


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Sh1!", "at least"),
        ("nouppercase1!", "uppercase"),
        ("NOLOWERCASE1!", "lower"),
        ("NoDigitsHere!", "digit"),
        ("NoSpecial1234", "special"),
    ],
)
def test_validate_password_rejects_weak_password(password, message):
    with pytest.raises(ValueError, match=message):
        validate_password(password)


def test_validate_email_normalizes_domain():
    assert validate_email("user@EXAMPLE.com") == "user@example.com"


@pytest.mark.parametrize("email", ["not-an-email", "user@", "@example.com"])
def test_validate_email_rejects_invalid_email(email):
    with pytest.raises(ValueError):
        validate_email(email)


# --- User model ---

def test_user_email_is_lowercased():
    user = User.create(email="Mixed.Case@Example.COM", raw_password="Valid1!pass", group_id=1)

    assert user.email == "mixed.case@example.com"


def test_user_password_is_hashed_and_write_only():
    user = User.create(email="u@example.com", raw_password="Valid1!pass", group_id=1)

    assert user._hashed_password != "Valid1!pass"
    assert user.verify_password("Valid1!pass")
    assert not user.verify_password("Wrong1!pass")
    with pytest.raises(AttributeError):
        _ = user.password


def test_user_password_setter_validates_complexity():
    user = User.create(email="u@example.com", raw_password="Valid1!pass", group_id=1)

    with pytest.raises(ValueError):
        user.password = "weak"


def test_user_has_group():
    user = User(email="u@example.com", group=UserGroup(name=UserGroupEnum.MODERATOR))

    assert user.has_group(UserGroupEnum.MODERATOR)
    assert not user.has_group(UserGroupEnum.ADMIN)


def test_group_ranks_are_ordered():
    assert UserGroupEnum.USER < UserGroupEnum.MODERATOR < UserGroupEnum.ADMIN


# --- token expiry ---

@pytest.mark.parametrize(
    ("delta", "expected"),
    [(timedelta(hours=1), True), (timedelta(hours=-1), False)],
)
def test_validate_token_by_time(delta, expected):
    token = ActivationToken(token="t", user_id=1, expires_at=datetime.now(timezone.utc) + delta)

    assert validate_token_by_time(token) is expected


def test_validate_token_by_time_handles_naive_datetime():
    # SQLite returns naive datetimes, they are treated as UTC
    naive_past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    token = ActivationToken(token="t", user_id=1, expires_at=naive_past)

    assert validate_token_by_time(token) is False


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(timedelta(hours=1), True), (timedelta(hours=-1), False)],
)
def test_refresh_token_validity(delta, expected):
    token = RefreshToken(token="t", user_id=1, expires_at=(datetime.now(timezone.utc) + delta).replace(tzinfo=None))

    assert token.check_if_token_is_valid() is expected


# --- JWT ---

def test_access_token_uses_default_lifetime():
    before = datetime.now(timezone.utc)

    payload = decode_access_token(create_access_token({"sub": "u@example.com"}))

    expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert payload["sub"] == "u@example.com"
    assert abs(expires - (before + settings.ACCESS_TOKEN_LIFETIME)) < timedelta(seconds=5)


def test_access_token_uses_custom_lifetime():
    before = datetime.now(timezone.utc)

    payload = decode_access_token(create_access_token({"sub": "u@example.com"}, expires_delta=timedelta(minutes=1)))

    expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert abs(expires - (before + timedelta(minutes=1))) < timedelta(seconds=5)
