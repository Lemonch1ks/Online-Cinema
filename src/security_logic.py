import jwt

from typing import Annotated
from datetime import datetime, timedelta, timezone

from jwt.exceptions import InvalidTokenError

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import base_app_settings
from sqlalchemy import select

from src.schemas.tokens import TokenData
from src.db.sqlite_session import get_sqlite_db
from src.db.models import User
from config.helper_functions import verify_password

SECRET_KEY = base_app_settings.SECRET_KEY
ALGORITHM = base_app_settings.ALGORITHM


password_hash = PasswordHash.recommended()

DUMMY_HASH = password_hash.hash("dummypassword")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=base_app_settings.SECURITY_TOKEN_URL + "/token")


async def get_user(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    item = await db.execute(stmt)
    user = item.scalar_one_or_none()
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user(db, email)
    if not user:
        verify_password(password, DUMMY_HASH)
        return None
    if not user.verify_password(password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + base_app_settings.ACCESS_TOKEN_LIFETIME
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: AsyncSession = Depends(get_sqlite_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except InvalidTokenError:
        raise credentials_exception
    user = await get_user(db=db, email=token_data.email)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return current_user
