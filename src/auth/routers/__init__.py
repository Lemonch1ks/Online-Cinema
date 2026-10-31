from fastapi import APIRouter

from src.auth.routers import accounts, tokens, users, admin
from src.core.config import settings

router = APIRouter()

router.include_router(tokens.router, prefix=settings.SECURITY_TOKEN_URL, tags=["security"])
router.include_router(users.router, prefix=f"{settings.API_VERSION_PREFIX}/users", tags=["users"])
router.include_router(accounts.router, prefix=f"{settings.API_VERSION_PREFIX}/accounts", tags=["accounts"])
router.include_router(admin.router, prefix=f"{settings.API_VERSION_PREFIX}/admins", tags=["admins"])
