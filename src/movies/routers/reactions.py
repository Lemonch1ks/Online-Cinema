from fastapi import APIRouter, Depends, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user
from src.auth.models import User
from src.core.database import get_db
from src.movies.models import MovieRating, MovieReaction
from src.movies.schemas import RatingInSchema, RatingSchema, ReactionInSchema, ReactionSchema
from src.movies.service import ensure_movie_exists

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "description": "Movie with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No movies with id:1 found."}}},
}


@router.put(
    "/movies/{movie_id}/reaction",
    response_model=ReactionSchema,
    summary="Like or Dislike a Movie",
    description="`is_like: true` is a like, `false` is a dislike. A new reaction replaces the previous one.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def set_reaction(
    movie_id: int,
    data: ReactionInSchema,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ReactionSchema:
    await ensure_movie_exists(db, movie_id)
    stmt = insert(MovieReaction).values(user_id=user.id, movie_id=movie_id, is_like=data.is_like)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["user_id", "movie_id"], set_={"is_like": stmt.excluded.is_like})
    )
    await db.commit()
    return ReactionSchema(movie_id=movie_id, is_like=data.is_like)


@router.delete(
    "/movies/{movie_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Like or Dislike",
    responses={404: NOT_FOUND_RESPONSE},
)
async def remove_reaction(
    movie_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ensure_movie_exists(db, movie_id)
    await db.execute(delete(MovieReaction).where(MovieReaction.user_id == user.id, MovieReaction.movie_id == movie_id))
    await db.commit()


@router.put(
    "/movies/{movie_id}/rating",
    response_model=RatingSchema,
    summary="Rate a Movie",
    description="A score from 1 to 10. A new score replaces the previous one.",
    responses={404: NOT_FOUND_RESPONSE},
)
async def set_rating(
    movie_id: int,
    data: RatingInSchema,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RatingSchema:
    await ensure_movie_exists(db, movie_id)
    stmt = insert(MovieRating).values(user_id=user.id, movie_id=movie_id, score=data.score)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["user_id", "movie_id"], set_={"score": stmt.excluded.score})
    )
    await db.commit()
    return RatingSchema(movie_id=movie_id, score=data.score)


@router.delete(
    "/movies/{movie_id}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Rating",
    responses={404: NOT_FOUND_RESPONSE},
)
async def remove_rating(
    movie_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ensure_movie_exists(db, movie_id)
    await db.execute(delete(MovieRating).where(MovieRating.user_id == user.id, MovieRating.movie_id == movie_id))
    await db.commit()
