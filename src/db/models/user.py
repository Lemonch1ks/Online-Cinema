from datetime import datetime, date

from enum import Enum

from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Enum as SQLEnum, func, Date
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Text

from src.db.models.base import Base

if TYPE_CHECKING:
    from src.db.models.tokens import ActivationToken, PasswordResetToken, RefreshToken


class UserGroupEnum(str, Enum):
    USER = 'USER'
    MODERATOR = 'MODERATOR'
    ADMIN = 'ADMIN'


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
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, unique=False, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, nullable=True, onupdate=func.now())
    group_id: Mapped[int] = mapped_column(ForeignKey('user_groups.id'))
    group: Mapped[UserGroup] = relationship(UserGroup, back_populates="users")
    user_profile: Mapped[Optional["UserProfile"]] = relationship("UserProfile", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    activation_token: Mapped[Optional["ActivationToken"]] = relationship("ActivationToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    password_reset_token: Mapped[Optional["PasswordResetToken"]] = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)


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
