from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user
from src.auth.models import User
from src.core.database import get_db
from src.movies.filters import MoviesQuery
from src.movies.models import Favorite, Movie
from src.movies.schemas import FavoriteSchema, MovieListResponseSchema
from src.movies.service import ensure_movie_exists, get_movies_page

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "description": "Movie with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No movies with id:1 found."}}},
}


@router.get(
    "/favorites",
    response_model=MovieListResponseSchema,
    summary="Get Favorite Movies",
    description="The current user's favorites with the same search, filters, sorting and pagination as the catalog.",
)
async def get_favorites(
    request: Request,
    query_params: Annotated[MoviesQuery, Query()],
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    stmt = select(Movie).join(Favorite, Favorite.movie_id == Movie.id).where(Favorite.user_id == user.id)
    return await get_movies_page(db, request, stmt, query_params)


@router.post(
    "/movies/{movie_id}/favorite",
    status_code=status.HTTP_201_CREATED,
    response_model=FavoriteSchema,
    summary="Add Movie to Favorites",
    description="Returns 201 when the movie is added and 200 when it was already in favorites.",
    responses={200: {"description": "The movie was already in favorites."}, 404: NOT_FOUND_RESPONSE},
)
async def add_favorite(
    movie_id: int,
    response: Response,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteSchema:
    await ensure_movie_exists(db, movie_id)
    stmt = (
        insert(Favorite)
        .values(user_id=user.id, movie_id=movie_id)
        .on_conflict_do_nothing()
        .returning(Favorite.movie_id)
    )
    added = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()

    if added is None:
        response.status_code = status.HTTP_200_OK
    return FavoriteSchema(movie_id=movie_id)


@router.delete(
    "/movies/{movie_id}/favorite",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Movie from Favorites",
    description="Also returns 204 when the movie was not in favorites.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def remove_favorite(
    movie_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ensure_movie_exists(db, movie_id)
    await db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.movie_id == movie_id))
    await db.commit()
