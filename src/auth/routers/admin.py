import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.auth.dependencies import require_role, get_current_active_user
from src.auth.models import UserGroupEnum, User, UserGroup
from src.auth.schemas import AdminChangeGroupSchema, AdminChangesUserSchema
from src.core.config import settings
from src.core.database import get_db
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import BaseEmailError, EmailSender

router = APIRouter(dependencies=[Depends(require_role(UserGroupEnum.ADMIN))])


logger = logging.getLogger(__name__)


@router.patch(
    "/users/{user_id}/group",
    summary="Update user group",
    response_model=AdminChangesUserSchema,
)
async def update_user_group(
        user_id: int,
        data: AdminChangeGroupSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot change itself group")

    user = (await db.execute(select(User).where(User.id == user_id).options(joinedload(User.group)))).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db_new_group = (await db.execute(select(UserGroup).where(UserGroup.name == data.new_group_rank.name))).scalar_one_or_none()

    if not db_new_group:
        raise HTTPException(status_code=404, detail="Group does not exist in db table")

    try:
        user.group = db_new_group
        await db.commit()
        return AdminChangesUserSchema.model_validate(user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during changing user group.",
        ) from e


@router.post(
    "/users/{user_id}/activate",
    summary="Activate user account",
)
async def activate_user_account(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSender = Depends(get_email_sender),
) -> AdminChangesUserSchema:
    user = (await db.execute(select(User).where(User.id == user_id).options(joinedload(User.activation_token), joinedload(User.group)))).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        return AdminChangesUserSchema.model_validate(user)

    user_email = user.email

    try:
        if user.activation_token:
            await db.delete(user.activation_token)
        user.is_active = True
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during changing user activation status.",
        ) from e

    login_link = settings.LOGIN_LINK_ENDPOINT
    try:
        await email_sender.send_activation_complete_email(user_email, login_link)
    except BaseEmailError:
        logger.exception("Failed to send activation complete email to %s", user_email)

    return AdminChangesUserSchema.model_validate(user)
