from typing import Annotated

from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy import insert, select, delete
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.dependencies import get_current_active_user
from src.auth.models import User, RefreshToken
from src.auth.schemas import Token, TokenVerifySchema
from src.auth.security import create_access_token, create_refresh_token
from src.auth.service import authenticate_user
from src.core.config import settings
from src.core.database import get_db

router = APIRouter()


@router.post("/token", description="Enter your email to 'username' field", summary="Login to get access and refresh tokens")
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
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token()
    stmt = insert(RefreshToken).values(token=refresh_token, user_id=user.id)

    await db.execute(stmt)
    await db.commit()

    return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token)


@router.post("/refresh", summary="Refresh your access token with refresh token")
async def token_refresh(
        current_token: TokenVerifySchema, db: AsyncSession = Depends(get_db),
) -> Token:
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.token == current_token.refresh_token)
        .options(selectinload(RefreshToken.user))
    )
    db_token = (await db.execute(stmt)).scalar_one_or_none()

    if not db_token or not db_token.check_if_token_is_valid():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not db_token.user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    access_token = create_access_token(
        data={"sub": db_token.user.email}, expires_delta=settings.ACCESS_TOKEN_LIFETIME
    )

    new_refresh_token = create_refresh_token()
    try:
        await db.delete(db_token)
        db.add(RefreshToken(token=new_refresh_token, user_id=db_token.user_id))
        await db.commit()
    except DatabaseError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Failed to refresh token") from e

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
        raise HTTPException(status_code=400, detail="Failed to logout") from e

    if result.rowcount == 0: # type: ignore
        raise HTTPException(status_code=401, detail="Invalid refresh token")
