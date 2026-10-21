from src.movies.schemas import (
    GenreDetailItemSchema,
    GenreListResponseSchema,
    GenreItemSchema
)

from src.movies.models import (
    Movie, Genre,
)

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from fastapi import APIRouter, Depends, HTTPException


router = APIRouter()


@router.get(
    "",
    response_model=GenreListResponseSchema,
    summary="Shows list of movie genres",
)
async def get_movie_genres(
        db: AsyncSession = Depends(get_db),
) -> GenreListResponseSchema:
    stmt = select(Genre, func.count(Movie.id).label("movies_count")).outerjoin(Genre.movies).group_by(Genre).order_by(Genre.id)

    items = await db.execute(stmt)
    genres = items.mappings().all()


    genre_list = [GenreItemSchema(
        id=genre["Genre"].id,
        name=genre["Genre"].name,
        movies_count=genre["movies_count"],
    ) for genre in genres]

    return GenreListResponseSchema(
        genres=genre_list,
    )


@router.get(
    "/{genre_id}",
    response_model=GenreDetailItemSchema,
    summary="Get genre Details",
    responses={
        404: {
            "description": "Genre with the given ID was not found.",
            "content": {
                "application/json": {
                    "example": {"detail": "No genre with id:1 found."}
                }
            },
        }
    }
)
async def get_genre_details(
        genre_id: int,
        db: AsyncSession = Depends(get_db),
) -> GenreDetailItemSchema:
    stmt = select(Genre).where(Genre.id == genre_id).options(selectinload(Genre.movies))
    item = await db.execute(stmt)
    genre = item.scalars().one_or_none()

    if genre is None:
        raise HTTPException(status_code=404, detail=f"No genre with id:{genre_id} found.")

    return GenreDetailItemSchema.model_validate(genre)
