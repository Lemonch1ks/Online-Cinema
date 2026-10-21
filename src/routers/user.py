import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


from src.security_logic import get_current_active_user
from src.notifications.helpers import create_and_send_an_activation_link
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import EmailSender
from src.db.models import ActivationToken, RefreshToken
from src.db.models.user import UserGroupEnum, UserGroup, User
from src.schemas.user import UserSchema, UserCreationSchema, UserChangePasswordSchema
from src.db.sqlite_session import get_sqlite_db


logger = logging.getLogger(__name__)

router = APIRouter()

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserSchema,
)
async def register_user(
        user_data: UserCreationSchema,
        db: AsyncSession = Depends(get_sqlite_db),
        email_sender: EmailSender = Depends(get_email_sender),
) -> UserSchema:

    act_token = secrets.token_urlsafe(32)

    stmt = select(User).where(User.email == user_data.email)

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        raise HTTPException(status_code=409, detail="User already exists")

    stmt = select(UserGroup).where(UserGroup.name == UserGroupEnum.USER)
    result = await db.execute(stmt)
    user_group = result.scalars().first()
    if not user_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found."
        )

    try:
        new_user = User.create(
            email=str(user_data.email),
            raw_password=user_data.password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()

        activation_token = ActivationToken(user_id=new_user.id, token=act_token)
        db.add(activation_token)

        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation."
        ) from e

    await create_and_send_an_activation_link(act_token=act_token, user=new_user, email_sender=email_sender)

    return UserSchema.model_validate(new_user)


@router.post(
    "/change_password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def change_password(
        user_data: UserChangePasswordSchema,
        user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_sqlite_db),
):
    if not user.verify_password(user_data.old_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credentials.")

    if user_data.new_password == user_data.old_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password cannot match the old one")

    try:
        user.password = user_data.new_password
        stmt = delete(RefreshToken).where(RefreshToken.user_id == user.id)
        await db.execute(stmt)
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password."
        )
