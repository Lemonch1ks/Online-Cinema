import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.notifications.helpers import validate_activation_token_by_time, create_and_send_an_activation_link
from config.settings import base_app_settings
from src.db.models import ActivationToken, User
from src.schemas.user import EmailRequestSchema
from src.db.sqlite_session import get_sqlite_db
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import EmailSender, BaseEmailError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/activate/{token}",
    summary="Activate user account",
    responses={
        400: {"description": "Activation token is invalid or expired."},
    },
)
async def activate_account(
        token: str,
        db: AsyncSession = Depends(get_sqlite_db),
        email_sender: EmailSender = Depends(get_email_sender),
) -> dict[str, str]:
    stmt = (
        select(ActivationToken)
        .where(ActivationToken.token == token)
        .options(selectinload(ActivationToken.user))
    )
    result = await db.execute(stmt)
    activation_token = result.scalar_one_or_none()

    if activation_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid activation token.",
        )

    if not validate_activation_token_by_time(activation_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Activation token has expired. Request a new one.",
        )

    user = activation_token.user
    user_email = user.email

    try:
        user.is_active = True
        await db.delete(activation_token)
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during account activation.",
        ) from e

    login_link = f"http://127.0.0.1{base_app_settings.SECURITY_TOKEN_URL}/token"
    try:
        await email_sender.send_activation_complete_email(user_email, login_link)
    except BaseEmailError:
        logger.exception("Failed to send activation complete email to %s", user_email)

    return {"detail": "Account activated successfully."}


@router.post(
    "/activate/resend",
    summary="Resend activation link",
    description=(
        "Sends a new activation link, valid for another 24 hours, if the email belongs "
        "to a registered, not yet activated account. The response is always the same, "
        "so it does not reveal which emails are registered."
    ),
)
async def resend_activation_link(
        data: EmailRequestSchema,
        db: AsyncSession = Depends(get_sqlite_db),
        email_sender: EmailSender = Depends(get_email_sender),
) -> dict[str, str]:
    response = {"detail": "If the account exists and is not activated, a new activation link has been sent."}

    stmt = (
        select(User)
        .where(User.email == data.email)
        .options(selectinload(User.activation_token))
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or user.is_active:
        return response

    new_token = secrets.token_urlsafe(32)

    try:
        if user.activation_token:
            user.activation_token.token = new_token
            user.activation_token.expires_at = (
                datetime.now(timezone.utc) + base_app_settings.ACTIVATION_TOKEN_LIFETIME
            )
        else:
            db.add(ActivationToken(user_id=user.id, token=new_token))
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating a new activation token.",
        ) from e

    await create_and_send_an_activation_link(act_token=new_token, user=user, email_sender=email_sender)

    return response
