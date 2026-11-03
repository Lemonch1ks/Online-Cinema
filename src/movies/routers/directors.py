from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.movies.dependencies import need_moderator
from src.movies.filters import BasePagination
from src.movies.models import Director, Movie
from src.movies.schemas import (
    DirectorDetailSchema,
    DirectorListResponseSchema,
    DirectorSchema,
    NamedItemSchema,
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
    "description": "Director with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No director with id:1 found."}}},
}
EXISTS_RESPONSE = {
    "description": "Director with this name already exists (case-insensitive).",
    "content": {"application/json": {"example": {"detail": "Director 'Name' already exists."}}},
}
IN_USE_RESPONSE = {
    "description": "Director is linked to movies.",
    "content": {"application/json": {"example": {"detail": "Director is used in 2 movies and cannot be deleted."}}},
}


@router.get(
    "",
    response_model=DirectorListResponseSchema,
    summary="Get Director List",
    description="Paginated list of directors ordered by name, with the number of movies of each.",
)
async def get_directors(
    request: Request,
    pagination: Annotated[BasePagination, Query()],
    db: AsyncSession = Depends(get_db),
) -> DirectorListResponseSchema:
    page, per_page = pagination.page, pagination.per_page
    total_items = (await db.execute(select(func.count()).select_from(Director))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    stmt = (
        select(Director.id, Director.name, func.count(Movie.id).label("movies_count"))
        .outerjoin(Director.movies)
        .group_by(Director.id)
        .order_by(Director.name, Director.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    directors = [NamedItemSchema.model_validate(dict(row)) for row in (await db.execute(stmt)).mappings()]

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return DirectorListResponseSchema(
        directors=directors,
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.get(
    "/{director_id}",
    response_model=DirectorDetailSchema,
    summary="Get Director Details",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_director_details(
    director_id: int,
    db: AsyncSession = Depends(get_db),
) -> DirectorDetailSchema:
    stmt = select(Director).where(Director.id == director_id).options(selectinload(Director.movies))
    director = (await db.execute(stmt)).scalars().one_or_none()
    if director is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No director with id:{director_id} found.")

    return DirectorDetailSchema.model_validate(director)


@router.post(
    "",
    dependencies=[need_moderator],
    status_code=status.HTTP_201_CREATED,
    response_model=DirectorSchema,
    summary="Create Director",
    responses={409: EXISTS_RESPONSE},
)
async def create_director(
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> DirectorSchema:
    await ensure_name_is_free(db, Director, data.name, "director")
    director = Director(name=data.name)
    db.add(director)
    await commit_or_409(db, duplicate_name_detail("director", data.name))

    return DirectorSchema.model_validate(director)


@router.patch(
    "/{director_id}",
    dependencies=[need_moderator],
    response_model=DirectorSchema,
    summary="Rename Director",
    responses={404: NOT_FOUND_RESPONSE, 409: EXISTS_RESPONSE},
)
async def rename_director(
    director_id: int,
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> DirectorSchema:
    director = await get_named_or_404(db, Director, director_id, "director")
    await ensure_name_is_free(db, Director, data.name, "director", exclude_id=director_id)
    director.name = data.name
    await commit_or_409(db, duplicate_name_detail("director", data.name))

    return DirectorSchema.model_validate(director)


@router.delete(
    "/{director_id}",
    dependencies=[need_moderator],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Director",
    description="A director that is linked to at least one movie cannot be deleted.",
    responses={404: NOT_FOUND_RESPONSE, 409: IN_USE_RESPONSE},
)
async def delete_director(
    director_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    director = await get_named_or_404(db, Director, director_id, "director")
    movies_count = await count_movies(db, Director, director_id)
    if movies_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Director is used in {movies_count} movies and cannot be deleted.",
        )

    await db.delete(director)
    await db.commit()
