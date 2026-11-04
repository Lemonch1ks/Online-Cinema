from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.movies.dependencies import need_moderator
from src.movies.filters import BasePagination
from src.movies.models import Movie, Star
from src.movies.schemas import (
    NamedItemSchema,
    NameInSchema,
    StarDetailSchema,
    StarListResponseSchema,
    StarSchema,
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
    "description": "Star with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No star with id:1 found."}}},
}
EXISTS_RESPONSE = {
    "description": "Star with this name already exists (case-insensitive).",
    "content": {"application/json": {"example": {"detail": "Star 'Name' already exists."}}},
}
IN_USE_RESPONSE = {
    "description": "Star is linked to movies.",
    "content": {"application/json": {"example": {"detail": "Star is used in 2 movies and cannot be deleted."}}},
}


@router.get(
    "",
    response_model=StarListResponseSchema,
    summary="Get Star List",
    description="Paginated list of stars ordered by name, with the number of movies of each.",
)
async def get_stars(
    request: Request,
    pagination: Annotated[BasePagination, Query()],
    db: AsyncSession = Depends(get_db),
) -> StarListResponseSchema:
    page, per_page = pagination.page, pagination.per_page
    total_items = (await db.execute(select(func.count()).select_from(Star))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    stmt = (
        select(Star.id, Star.name, func.count(Movie.id).label("movies_count"))
        .outerjoin(Star.movies)
        .group_by(Star.id)
        .order_by(Star.name, Star.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    stars = [NamedItemSchema.model_validate(dict(row)) for row in (await db.execute(stmt)).mappings()]

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return StarListResponseSchema(
        stars=stars,
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.get(
    "/{star_id}",
    response_model=StarDetailSchema,
    summary="Get Star Details",
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_star_details(
    star_id: int,
    db: AsyncSession = Depends(get_db),
) -> StarDetailSchema:
    stmt = select(Star).where(Star.id == star_id).options(selectinload(Star.movies))
    star = (await db.execute(stmt)).scalars().one_or_none()
    if star is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No star with id:{star_id} found.")

    return StarDetailSchema.model_validate(star)


@router.post(
    "",
    dependencies=[need_moderator],
    status_code=status.HTTP_201_CREATED,
    response_model=StarSchema,
    summary="Create Star",
    responses={409: EXISTS_RESPONSE},
)
async def create_star(
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> StarSchema:
    await ensure_name_is_free(db, Star, data.name, "star")
    star = Star(name=data.name)
    db.add(star)
    await commit_or_409(db, duplicate_name_detail("star", data.name))

    return StarSchema.model_validate(star)


@router.patch(
    "/{star_id}",
    dependencies=[need_moderator],
    response_model=StarSchema,
    summary="Rename Star",
    responses={404: NOT_FOUND_RESPONSE, 409: EXISTS_RESPONSE},
)
async def rename_star(
    star_id: int,
    data: NameInSchema,
    db: AsyncSession = Depends(get_db),
) -> StarSchema:
    star = await get_named_or_404(db, Star, star_id, "star")
    await ensure_name_is_free(db, Star, data.name, "star", exclude_id=star_id)
    star.name = data.name
    await commit_or_409(db, duplicate_name_detail("star", data.name))

    return StarSchema.model_validate(star)


@router.delete(
    "/{star_id}",
    dependencies=[need_moderator],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Star",
    description="A star that is linked to at least one movie cannot be deleted.",
    responses={404: NOT_FOUND_RESPONSE, 409: IN_USE_RESPONSE},
)
async def delete_star(
    star_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    star = await get_named_or_404(db, Star, star_id, "star")
    movies_count = await count_movies(db, Star, star_id)
    if movies_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Star is used in {movies_count} movies and cannot be deleted.",
        )

    await db.delete(star)
    await db.commit()
