from typing import Annotated

from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import base_app_settings

from src.db.models import User
from src.db.sqlite_session import get_sqlite_db
from src.security_logic import authenticate_user, create_access_token, get_current_active_user
from src.schemas.user import UserSchema
from src.schemas.tokens import Token

router = APIRouter()


@router.post("/token", description="Enter your email to 'username' field")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_sqlite_db),
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

    access_token_expires = base_app_settings.ACCESS_TOKEN_LIFETIME
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/users/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserSchema:
    return current_user
