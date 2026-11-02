from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, insert
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user
from src.auth.models import RefreshToken, User
from src.auth.schemas import Token, TokenVerifySchema
from src.auth.security import create_access_token, create_refresh_token
from src.auth.service import authenticate_user
from src.core.config import settings
from src.core.database import get_db

router = APIRouter()


@router.post(
    "/token", description="Enter your email to 'username' field", summary="Login to get access and refresh tokens"
)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await authenticate_user(db, form_data.username.lower(), form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    access_token_expires = settings.ACCESS_TOKEN_LIFETIME
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    refresh_token = create_refresh_token()
    stmt = insert(RefreshToken).values(token=refresh_token, user_id=user.id)

    await db.execute(stmt)
    await db.commit()

    return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token)


@router.post("/refresh", summary="Refresh your access token with refresh token")
async def token_refresh(
    current_token: TokenVerifySchema,
    db: AsyncSession = Depends(get_db),
) -> Token:
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    stmt = (
        delete(RefreshToken)
        .where(RefreshToken.token == current_token.refresh_token)
        .returning(RefreshToken.user_id, RefreshToken.expires_at)
    )
    try:
        used_token = (await db.execute(stmt)).one_or_none()
    except DatabaseError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh token") from e

    if used_token is None:
        raise invalid_token

    if used_token.expires_at < datetime.now(UTC):
        await db.rollback()
        raise invalid_token

    user = await db.get(User, used_token.user_id)
    if not user.is_active:
        await db.rollback()
        raise HTTPException(status_code=403, detail="Inactive user")

    access_token = create_access_token(data={"sub": user.email}, expires_delta=settings.ACCESS_TOKEN_LIFETIME)

    new_refresh_token = create_refresh_token()
    try:
        db.add(RefreshToken(token=new_refresh_token, user_id=user.id))
        await db.commit()
    except DatabaseError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh token") from e

    return Token(access_token=access_token, token_type="bearer", refresh_token=new_refresh_token)


@router.post("/logout", summary="Log out (revokes the given refresh token)", status_code=204)
async def users_logout(
    current_user: Annotated[User, Depends(get_current_active_user)],
    refresh_token: TokenVerifySchema,
    db: AsyncSession = Depends(get_db),
) -> None:
    stmt = delete(RefreshToken).where(
        RefreshToken.user_id == current_user.id,
        RefreshToken.token == refresh_token.refresh_token,
    )

    try:
        result = await db.execute(stmt)
        await db.commit()
    except DatabaseError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to logout") from e

    if result.rowcount == 0:  # type: ignore
        raise HTTPException(status_code=401, detail="Invalid refresh token")
