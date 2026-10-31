from datetime import datetime, date, timezone

from enum import Enum

from typing import List, Optional
from sqlalchemy import Enum as SQLEnum, func, Date
from sqlalchemy.orm import mapped_column, Mapped, relationship, validates
from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Text

from src.auth.security import get_password_hash, verify_password
from src.auth.validators import validate_email, validate_password
from src.core.config import settings
from src.core.database import Base


class UserGroupEnum(int, Enum):
    USER = 1
    MODERATOR = 5
    ADMIN = 10


class GenderEnum(str, Enum):
    MAN = 'MAN'
    WOMAN = 'WOMAN'


class UserGroup(Base):
    __tablename__ = "user_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[UserGroupEnum] = mapped_column(SQLEnum(UserGroupEnum), nullable=False, unique=True)
    users: Mapped[List["User"]] = relationship("User", back_populates="group")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    _hashed_password: Mapped[str] = mapped_column("hashed_password",String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, unique=False, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, nullable=True, onupdate=func.now())
    group_id: Mapped[int] = mapped_column(ForeignKey('user_groups.id'))
    group: Mapped[UserGroup] = relationship(UserGroup, back_populates="users")
    user_profile: Mapped[Optional["UserProfile"]] = relationship("UserProfile", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    activation_token: Mapped[Optional["ActivationToken"]] = relationship("ActivationToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    password_reset_token: Mapped[Optional["PasswordResetToken"]] = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    def has_group(self, group_name: UserGroupEnum) -> bool:
        return self.group.name == group_name

    @property
    def password(self) -> None:
        raise AttributeError("Password is write-only. Use the setter to set the password.")

    @password.setter
    def password(self, raw_password: str) -> None:
        validate_password(raw_password)
        self._hashed_password = get_password_hash(raw_password)

    def verify_password(self, raw_password: str) -> bool:
        return verify_password(raw_password, self._hashed_password)

    @validates("email")
    def validate_email(self, key, value):
        return validate_email(value.lower())

    @classmethod
    def create(cls, email: str, raw_password: str, group_id: int) -> User:
        user = cls(email=email, group_id=group_id)
        user.password = raw_password
        return user


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete="CASCADE"), unique=True)
    user: Mapped[User] = relationship("User", back_populates="user_profile")
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String, nullable=True)
    gender: Mapped[GenderEnum | None] = mapped_column(SQLEnum(GenderEnum), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)


class ActivationToken(Base):
    __tablename__ = "activation_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete="CASCADE"), unique=True, nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="activation_token")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + settings.ACTIVATION_TOKEN_LIFETIME)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="password_reset_token")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + settings.PASSWORD_RESET_TOKEN_LIFETIME)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + settings.REFRESH_TOKEN_LIFETIME)

    def check_if_token_is_valid(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            return False
        return True
