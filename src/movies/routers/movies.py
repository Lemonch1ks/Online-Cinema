from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.movies.dependencies import need_moderator
from src.movies.filters import MoviesQuery
from src.movies.models import Certification, Director, Genre, Movie, Star
from src.movies.schemas import (
    MovieCreationSchema,
    MovieDetailItemSchema,
    MovieListItemSchema,
    MovieListResponseSchema,
    MovieUpdateSchema,
)
from src.movies.service import commit_or_409, get_or_create_by_names

router = APIRouter()

DUPLICATE_MOVIE_DETAIL = "A movie with this name, year and time already exists."


@router.get(
    "",
    response_model=MovieListResponseSchema,
    summary="Get Movie List",
    description=(
        "<h3>This endpoint retrieves a paginated list of movies from the database. "
        "Clients can specify the `page` number and the number of items per page using `per_page`. "
        "Clients can use filters with query params"
        "The response includes details about the movies, total pages, and total items, "
        "along with links to the previous and next pages if applicable.</h3>"
    ),
)
async def get_movies(
    request: Request,
    query_params: Annotated[MoviesQuery, Query()],
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:

    page = query_params.page
    per_page = query_params.per_page

    stmt = select(Movie)

    stmt = query_params.search(stmt)
    stmt = query_params.filter(stmt)

    offset = (page - 1) * per_page

    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total_items = result_count.scalar() or 0

    stmt = query_params.sort(stmt)

    items = await db.execute(stmt.order_by(Movie.id).offset(offset).limit(per_page))
    movies = items.scalars().all()

    total_pages = (total_items + per_page - 1) // per_page

    movie_list = [MovieListItemSchema.model_validate(movie) for movie in movies]

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return MovieListResponseSchema(
        movies=movie_list,
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


NOT_FOUND_RESPONSE = {
    "description": "Movie with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No movies with id:1 found."}}},
}
CONFLICT_RESPONSE = {
    "description": "A movie with the same name, year and time already exists.",
    "content": {"application/json": {"example": {"detail": DUPLICATE_MOVIE_DETAIL}}},
}


async def get_movie_or_404(db: AsyncSession, movie_id: int) -> Movie:
    stmt = (
        select(Movie)
        .where(Movie.id == movie_id)
        .options(
            selectinload(Movie.stars),
            selectinload(Movie.directors),
            selectinload(Movie.genres),
        )
    )
    movie = (await db.execute(stmt)).scalars().one_or_none()
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No movies with id:{movie_id} found.")
    return movie


@router.get(
    "/{movie_id}",
    response_model=MovieDetailItemSchema,
    summary="Get Movie Details",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_movie_details(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
) -> MovieDetailItemSchema:
    movie = await get_movie_or_404(db, movie_id)
    return MovieDetailItemSchema.model_validate(movie)


@router.post(
    "",
    dependencies=[need_moderator],
    status_code=status.HTTP_201_CREATED,
    response_model=MovieDetailItemSchema,
    summary="Create Movie",
    description=(
        "Genres, stars, directors and certification are passed by name. "
        "Existing ones are found ignoring case, missing ones are created."
    ),
    responses={409: CONFLICT_RESPONSE},
)
async def create_movie(
    new_data: MovieCreationSchema,
    db: AsyncSession = Depends(get_db),
) -> MovieDetailItemSchema:
    fields = new_data.model_dump(exclude={"certification", "genres", "stars", "directors"})
    [certification] = await get_or_create_by_names(db, Certification, [new_data.certification])
    movie = Movie(
        **fields,
        certification=certification,
        genres=await get_or_create_by_names(db, Genre, new_data.genres),
        stars=await get_or_create_by_names(db, Star, new_data.stars),
        directors=await get_or_create_by_names(db, Director, new_data.directors),
    )
    db.add(movie)
    await commit_or_409(db, DUPLICATE_MOVIE_DETAIL)

    return MovieDetailItemSchema.model_validate(movie)


@router.patch(
    "/{movie_id}",
    dependencies=[need_moderator],
    response_model=MovieDetailItemSchema,
    summary="Update Movie",
    description=(
        "Only the passed fields are changed. "
        "A passed list of genres, stars or directors replaces the current one entirely."
    ),
    responses={404: NOT_FOUND_RESPONSE, 409: CONFLICT_RESPONSE},
)
async def update_movie(
    movie_id: int,
    data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
) -> MovieDetailItemSchema:
    movie = await get_movie_or_404(db, movie_id)
    changes = data.model_dump(exclude_unset=True)

    if "certification" in changes:
        [changes["certification"]] = await get_or_create_by_names(db, Certification, [changes["certification"]])
    for field, model in (("genres", Genre), ("stars", Star), ("directors", Director)):
        if field in changes:
            changes[field] = await get_or_create_by_names(db, model, changes[field])

    for field, value in changes.items():
        setattr(movie, field, value)
    await commit_or_409(db, DUPLICATE_MOVIE_DETAIL)

    return MovieDetailItemSchema.model_validate(movie)


@router.delete(
    "/{movie_id}",
    dependencies=[need_moderator],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Movie",
    responses={404: NOT_FOUND_RESPONSE},
)
async def delete_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    movie = await get_movie_or_404(db, movie_id)
    await db.delete(movie)
    await db.commit()
