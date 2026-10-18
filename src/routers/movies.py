from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.filters import MoviesQuery
from src.db.sqlite_session import get_sqlite_db

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from src.db.models.movies import (
    Movie,
)

from src.schemas.movies import (
    MovieListResponseSchema,
    MovieListItemSchema,
    MovieDetailItemSchema,
)


from fastapi import APIRouter, Query, Depends, HTTPException, Request


router = APIRouter()


@router.get(
    "/",
    response_model=MovieListResponseSchema,
    summary="Get Movie List",
    description=(
            "<h3>This endpoint retrieves a paginated list of movies from the database. "
            "Clients can specify the `page` number and the number of items per page using `per_page`. "
            "Clients can use filters with query params"
            "The response includes details about the movies, total pages, and total items, "
            "along with links to the previous and next pages if applicable.</h3>"
    ),
    responses={
        404: {
            "description": "No movies found.",
            "content": {
                "application/json": {
                    "example": {"detail": "No movies found."}
                }
            },
        }
    }
)
async def get_movies(
        request: Request,
        query_params: Annotated[MoviesQuery, Query()],
        db: AsyncSession = Depends(get_sqlite_db),
) -> MovieListResponseSchema:

    page = query_params.page
    per_page = query_params.per_page

    stmt = select(Movie)

    stmt = query_params.filter(stmt)


    offset = (page - 1) * per_page

    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total_items = result_count.scalar() or 0

    if not total_items:
        raise HTTPException(status_code=404, detail="No movies found.")

    stmt = query_params.sort(stmt)

    items = await db.execute(stmt.order_by(Movie.id).offset(offset).limit(per_page))
    movies = items.scalars().all()

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")

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


@router.get(
    "/{movie_id}",
    response_model=MovieDetailItemSchema,
    summary="Get Movie Details",
    responses={
        404: {
            "description": "Movie with the given ID was not found.",
            "content": {
                "application/json": {
                    "example": {"detail": "No movies with id:1 found."}
                }
            },
        }
    }
)
async def get_movie_details(
        movie_id: int,
        db: AsyncSession = Depends(get_sqlite_db),
) -> MovieDetailItemSchema:
    stmt = (
        select(Movie)
        .where(Movie.id == movie_id)
        .options(
            selectinload(Movie.stars),
            selectinload(Movie.directors),
            selectinload(Movie.genres),
        )
    )

    item = await db.execute(stmt)
    movie = item.scalars().one_or_none()
    if movie is None:
        raise HTTPException(status_code=404, detail=f"No movies with id:{movie_id} found.")

    return MovieDetailItemSchema.model_validate(movie)
