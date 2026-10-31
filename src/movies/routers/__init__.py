from fastapi import APIRouter

from src.core.config import settings
from src.movies.routers import genres, movies

router = APIRouter()

router.include_router(movies.router, prefix=f"{settings.API_VERSION_PREFIX}/movies", tags=["movies"])
router.include_router(genres.router, prefix=f"{settings.API_VERSION_PREFIX}/genres", tags=["genres"])
