from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.movies.dependencies import need_moderator
from src.movies.models import (
    Genre,
    Movie,
)
from src.movies.schemas import (
    GenreDetailItemSchema,
    GenreItemSchema,
    GenreListResponseSchema,
    GenreSchema,
    NameInSchema,
)
from src.movies.service import (
    commit_or_409,
    count_movies,
    duplicate_name_detail,
    ensure_name_is_free,
    get_named_or_404,
)

router = APIRouter()

NOT_FOUND_RESPONSE = {
    "description": "Genre with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No genre with id:1 found."}}},
}
EXISTS_RESPONSE = {
    "description": "Genre with this name already exists (case-insensitive).",
    "content": {"application/json": {"example": {"detail": "Genre 'Name' already exists."}}},
}
IN_USE_RESPONSE = {
    "description": "Genre is linked to movies.",
    "content": {"application/json": {"example": {"detail": "Genre is used in 2 movies and cannot be deleted."}}},
}


@router.get(
    "",
    response_model=GenreListResponseSchema,
    summary="Shows list of movie genres",
)
async def get_movie_genres(
    db: AsyncSession = Depends(get_db),
) -> GenreListResponseSchema:
    stmt = (
        select(Genre, func.count(Movie.id).label("movies_count"))
        .outerjoin(Genre.movies)
        .group_by(Genre.id)
        .order_by(Genre.id)
    )

    items = await db.execute(stmt)
    genres = items.mappings().all()

    genre_list = [
        GenreItemSchema(
            id=genre["Genre"].id,
            name=genre["Genre"].name,
            movies_count=genre["movies_count"],
        )
        for genre in genres
    ]

    return GenreListResponseSchema(
        genres=genre_list,
    )


@router.get(
    "/{genre_id}",
    response_model=GenreDetailItemSchema,
    summary="Get genre Details",
    responses={404: NOT_FOUND_RESPONSE},
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


@router.post(
    "",
    dependencies=[need_moderator],
    status_code=status.HTTP_201_CREATED,
    response_model=GenreSchema,
    summary="Create Genre",
    responses={409: EXISTS_RESPONSE},
)
async def create_genre(
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> GenreSchema:
    await ensure_name_is_free(db, Genre, data.name, "genre")
    genre = Genre(name=data.name)
    db.add(genre)
    await commit_or_409(db, duplicate_name_detail("genre", data.name))

    return GenreSchema.model_validate(genre)


@router.patch(
    "/{genre_id}",
    dependencies=[need_moderator],
    response_model=GenreSchema,
    summary="Rename Genre",
    responses={404: NOT_FOUND_RESPONSE, 409: EXISTS_RESPONSE},
)
async def rename_genre(
    genre_id: int,
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> GenreSchema:
    genre = await get_named_or_404(db, Genre, genre_id, "genre")
    await ensure_name_is_free(db, Genre, data.name, "genre", exclude_id=genre_id)
    genre.name = data.name
    await commit_or_409(db, duplicate_name_detail("genre", data.name))

    return GenreSchema.model_validate(genre)


@router.delete(
    "/{genre_id}",
    dependencies=[need_moderator],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Genre",
    description="A genre that is linked to at least one movie cannot be deleted.",
    responses={404: NOT_FOUND_RESPONSE, 409: IN_USE_RESPONSE},
)
async def delete_genre(
    genre_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    genre = await get_named_or_404(db, Genre, genre_id, "genre")
    movies_count = await count_movies(db, Genre, genre_id)
    if movies_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Genre is used in {movies_count} movies and cannot be deleted.",
        )

    await db.delete(genre)
    await db.commit()
