from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import mapped_column, Mapped, relationship

from config.settings import base_app_settings

from src.db.models.base import Base

if TYPE_CHECKING:
    from src.db.models.user import User


class ActivationToken(Base):
    __tablename__ = "activation_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete="CASCADE"), unique=True, nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="activation_token")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + base_app_settings.ACTIVATION_TOKEN_LIFETIME)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="password_reset_token")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + base_app_settings.PASSWORD_RESET_TOKEN_LIFETIME)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=False, default=lambda: datetime.now(timezone.utc) + base_app_settings.REFRESH_TOKEN_LIFETIME)

    def check_if_token_is_valid(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            return False
        return True
