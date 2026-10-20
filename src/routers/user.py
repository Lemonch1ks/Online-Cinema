import logging
import secrets

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import base_app_settings
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import EmailSender, BaseEmailError
from src.db.models import ActivationToken
from src.db.models.user import UserGroupEnum, UserGroup, User
from src.schemas.user import UserSchema, UserCreationSchema
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

    activation_link = f"http://127.0.0.1{base_app_settings.ACTIVATION_LINK_BASE}{act_token}"
    try:
        await email_sender.send_activation_email(new_user.email, activation_link)
    except BaseEmailError:
        logger.exception("Failed to send activation email to %s", new_user.email)

    return UserSchema.model_validate(new_user)
