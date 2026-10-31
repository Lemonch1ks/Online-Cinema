from fastapi import FastAPI

from src.auth.routers import router as auth_router
from src.core.config import settings
from src.movies.routers import router as movies_router

app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
)

app.include_router(auth_router)
app.include_router(movies_router)
