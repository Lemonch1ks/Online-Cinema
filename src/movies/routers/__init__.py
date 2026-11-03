from fastapi import APIRouter

from src.core.config import settings
from src.movies.routers import directors, genres, movies, stars

router = APIRouter()

router.include_router(movies.router, prefix=f"{settings.API_VERSION_PREFIX}/movies", tags=["movies"])
router.include_router(genres.router, prefix=f"{settings.API_VERSION_PREFIX}/genres", tags=["genres"])
router.include_router(stars.router, prefix=f"{settings.API_VERSION_PREFIX}/stars", tags=["stars"])
router.include_router(directors.router, prefix=f"{settings.API_VERSION_PREFIX}/directors", tags=["directors"])
