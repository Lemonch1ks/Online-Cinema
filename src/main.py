from fastapi import FastAPI

from src.routers.movies import router as movie_router
from src.routers.genres import router as genre_router

app = FastAPI(
    title="Movie API",
    description="Movie API",
    version="1.0.0",
)

api_version_prefix = "/api/v1"

app.include_router(movie_router, prefix=f"{api_version_prefix}/movies", tags=["movies"])
app.include_router(genre_router, prefix=f"{api_version_prefix}/genres", tags=["genres"])
