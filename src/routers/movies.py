from sqlalchemy.ext.asyncio import AsyncSession
from src.db.sqlite_session import get_sqlite_db

from sqlalchemy import select, func


from src.db.models.movies import (
    Movie,
)

from src.schemas import (
    MovieListResponseSchema,
    MovieListItemSchema,
    MoviDetailItemSchema,
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
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(10, ge=1, le=20, description="Number of items per page"),
        db: AsyncSession = Depends(get_sqlite_db),
) -> MovieListResponseSchema:
    offset = (page - 1) * per_page


    count_stmt = select(func.count(Movie.id))
    result_count = await db.execute(count_stmt)
    total_items = result_count.scalar() or 0

    if not total_items:
        raise HTTPException(status_code=404, detail="No movies found.")

    stmt = select(Movie)

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


