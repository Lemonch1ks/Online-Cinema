from fastapi import FastAPI

from config.settings import base_app_settings

from src.routers.movies import router as movie_router
from src.routers.genres import router as genre_router
from src.routers.security import router as security_router

app = FastAPI(
    title="Movie API",
    description="Movie API",
    version="1.0.0",
)

api_version_prefix = base_app_settings.API_VERSION_PREFIX


app.include_router(movie_router, prefix=f"{api_version_prefix}/movies", tags=["movies"])
app.include_router(genre_router, prefix=f"{api_version_prefix}/genres", tags=["genres"])
app.include_router(security_router, prefix=base_app_settings.SECURITY_TOKEN_URL, tags=["security"])
