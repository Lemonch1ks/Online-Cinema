from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials, OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User, UserGroupEnum
from src.auth.schemas import TokenData
from src.auth.security import decode_access_token
from src.auth.service import authenticate_user, get_user
from src.core.config import settings
from src.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=settings.SECURITY_TOKEN_URL + "/token")
docs_basic_auth = HTTPBasic(realm="API docs")


async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)],
        db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
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


def require_role(min_role: UserGroupEnum):
    async def checker(user: User = Depends(get_current_active_user)) -> User:
        if user.group.name < min_role:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return user

    return checker


async def verify_docs_access(
        credentials: Annotated[HTTPBasicCredentials, Depends(docs_basic_auth)],
        db: AsyncSession = Depends(get_db),
) -> User:
    user = await authenticate_user(db, credentials.username.lower(), credentials.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": 'Basic realm="API docs"'},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user
