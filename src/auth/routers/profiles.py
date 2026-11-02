import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user
from src.auth.models import User, UserProfile
from src.auth.schemas import ProfileFormSchema, ProfileSchema
from src.auth.validators import validate_avatar
from src.core.config import settings
from src.core.database import get_db
from src.storage.dependencies import get_storage
from src.storage.s3 import S3Storage, StorageError

logger = logging.getLogger(__name__)

router = APIRouter()

EXTENSIONS = {"JPEG": "jpg"}

PROFILE_NOT_FOUND = {404: {"description": "You have no profile yet."}}
UPLOAD_FAILED = {500: {"description": "The avatar could not be uploaded or the profile could not be saved."}}


async def get_profile(db: AsyncSession, user: User) -> UserProfile | None:
    stmt = select(UserProfile).where(UserProfile.user_id == user.id)
    return (await db.execute(stmt)).scalar_one_or_none()


def to_schema(profile: UserProfile, storage: S3Storage) -> ProfileSchema:
    return ProfileSchema(
        id=profile.id,
        user_id=profile.user_id,
        first_name=profile.first_name,
        last_name=profile.last_name,
        gender=profile.gender,
        date_of_birth=profile.date_of_birth,
        info=profile.info,
        avatar_url=storage.url(profile.avatar) if profile.avatar else None,
    )


async def upload_avatar(avatar: UploadFile, user: User, storage: S3Storage) -> str:
    """Validate the file, upload it and return its storage key."""
    data = await avatar.read(settings.AVATAR_MAX_SIZE + 1)
    try:
        image_format = validate_avatar(data)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error

    key = f"{user.id}/{uuid4().hex}.{EXTENSIONS.get(image_format, image_format.lower())}"
    try:
        await storage.upload(key, data, content_type=Image.MIME[image_format])
    except StorageError as error:
        logger.exception("Failed to upload avatar for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload the avatar. Please try again later.",
        ) from error
    return key


async def delete_avatar_quietly(storage: S3Storage, key: str) -> None:
    """Cleanup of a file nobody points to: a failure here must not fail the request, it is only logged."""
    try:
        await storage.delete(key)
    except StorageError:
        logger.exception("Failed to delete avatar %s", key)


@router.post(
    "/me",
    response_model=ProfileSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create your profile",
    responses={409: {"description": "You already have a profile."}, **UPLOAD_FAILED},
)
async def create_profile(
        data: Annotated[ProfileFormSchema, Form()],
        user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
        storage: S3Storage = Depends(get_storage),
) -> ProfileSchema:
    if await get_profile(db, user) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have a profile.")

    avatar_key = await upload_avatar(data.avatar, user, storage) if data.avatar else None
    profile = UserProfile(user_id=user.id, avatar=avatar_key, **data.model_dump(exclude={"avatar"}))
    db.add(profile)
    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        if avatar_key:
            await delete_avatar_quietly(storage, avatar_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the profile.",
        ) from error

    return to_schema(profile, storage)


@router.get("/me", response_model=ProfileSchema, summary="Get your profile", responses=PROFILE_NOT_FOUND)
async def read_profile(
        user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
        storage: S3Storage = Depends(get_storage),
) -> ProfileSchema:
    profile = await get_profile(db, user)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You have no profile yet.")
    return to_schema(profile, storage)


@router.patch(
    "/me",
    response_model=ProfileSchema,
    summary="Update your profile",
    description="Only the sent fields are changed. Sending an avatar replaces the old one.",
    responses={**PROFILE_NOT_FOUND, **UPLOAD_FAILED},
)
async def update_profile(
        data: Annotated[ProfileFormSchema, Form()],
        user: Annotated[User, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
        storage: S3Storage = Depends(get_storage),
) -> ProfileSchema:
    profile = await get_profile(db, user)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You have no profile yet.")

    for field in data.model_fields_set - {"avatar"}:
        setattr(profile, field, getattr(data, field))

    old_key = profile.avatar
    new_key = await upload_avatar(data.avatar, user, storage) if data.avatar else None
    if new_key:
        profile.avatar = new_key

    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        if new_key:
            await delete_avatar_quietly(storage, new_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the profile.",
        ) from error

    if new_key and old_key:
        await delete_avatar_quietly(storage, old_key)

    return to_schema(profile, storage)
