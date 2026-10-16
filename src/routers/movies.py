from sqlalchemy.ext.asyncio import AsyncSession
from db import get_sqlite_db

from sqlalchemy import select, func

from db.models import (
    Movie,
)

from schemas import (
    MoviDetailsSchema,
    MovieListResponseSchema,
)
from fastapi import APIRouter, Query, Depends, HTTPException

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
        page: int = Query(0, ge=1, description="Page number"),
        per_page: int = Query(10, ge=1, le=20, description="Number of items per page"),
        db: AsyncSession = Depends(get_sqlite_db)
) -> MovieListResponseSchema:
    offset = (page - 1) * per_page

    count_stmt = select(func.count(Movie.id))
    result_count = await db.execute(count_stmt)
    total_items = result_count.scalar() or 0

    if not total_items:
        raise HTTPException(status_code=404, detail="No movies found.")

    items = await db.execute(select(Movie).offset(offset).limit(per_page))
    movies = [items.scalars().all()]

    if not items:
        raise HTTPException(status_code=404, detail="No movies found.")

    return MovieListResponseSchema(
        movies=movies,
        next_page=str(page + 1),
        prev_page=str(page - 1),
        total_pages=total_items // per_page,
        total_items=total_items,
    )
