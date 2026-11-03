from fastapi import HTTPException, Request, status
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.movies.filters import MoviesQuery
from src.movies.models import Certification, Director, Genre, Movie, MovieRating, MovieReaction, Star
from src.movies.schemas import MovieDetailItemSchema, MovieListItemSchema, MovieListResponseSchema


async def get_or_create_by_names[T: (Genre, Star, Director, Certification)](
    db: AsyncSession, model: type[T], names: list[str]
) -> list[T]:
    """Finds records by name ignoring case and creates the missing ones. Keeps the order of `names`."""
    if not names:
        return []

    stmt = select(model).where(func.lower(model.name).in_([name.lower() for name in names]))
    found = {obj.name.lower(): obj for obj in await db.scalars(stmt)}

    missing = [name for name in names if name.lower() not in found]
    if missing:
        await db.execute(
            insert(model).values([{"name": name} for name in missing]).on_conflict_do_nothing(index_elements=["name"])
        )
        created = await db.scalars(select(model).where(model.name.in_(missing)))
        found.update({obj.name.lower(): obj for obj in created})

    return [found[name.lower()] for name in names]


async def commit_or_409(db: AsyncSession, detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from error


async def get_named_or_404[T: (Genre, Star, Director)](
    db: AsyncSession, model: type[T], record_id: int, label: str
) -> T:
    record = await db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No {label} with id:{record_id} found.")
    return record


async def ensure_name_is_free[T: (Genre, Star, Director)](
    db: AsyncSession, model: type[T], name: str, label: str, exclude_id: int | None = None
) -> None:
    stmt = select(model.id).where(func.lower(model.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if await db.scalar(stmt) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=duplicate_name_detail(label, name))


def duplicate_name_detail(label: str, name: str) -> str:
    return f"{label.capitalize()} '{name}' already exists."


async def count_movies[T: (Genre, Star, Director)](db: AsyncSession, model: type[T], record_id: int) -> int:
    stmt = select(func.count(Movie.id)).join(model.movies).where(model.id == record_id)
    return (await db.execute(stmt)).scalar_one()


async def get_movies_page(
    db: AsyncSession, request: Request, stmt: Select, query: MoviesQuery
) -> MovieListResponseSchema:
    """One page of a movie catalog: search, filters, sorting and pagination on top of `stmt`.

    `stmt` selects the movies to start from: the whole catalog or, for example, a user's favorites.
    """
    page, per_page = query.page, query.per_page
    stmt = query.filter(query.search(stmt))

    total_items = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    stmt = query.sort(stmt).order_by(Movie.id).offset((page - 1) * per_page).limit(per_page)
    movies = [MovieListItemSchema.model_validate(movie) for movie in await db.scalars(stmt)]

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return MovieListResponseSchema(
        movies=movies,
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


async def ensure_movie_exists(db: AsyncSession, movie_id: int) -> None:
    if await db.scalar(select(Movie.id).where(Movie.id == movie_id)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No movies with id:{movie_id} found.")


async def movie_details(db: AsyncSession, movie: Movie) -> MovieDetailItemSchema:
    """Movie details with likes, dislikes and the average rating of our users."""
    likes, dislikes = (
        await db.execute(
            select(
                func.count().filter(MovieReaction.is_like.is_(True)),
                func.count().filter(MovieReaction.is_like.is_(False)),
            ).where(MovieReaction.movie_id == movie.id)
        )
    ).one()
    rating_avg, rating_count = (
        await db.execute(select(func.avg(MovieRating.score), func.count()).where(MovieRating.movie_id == movie.id))
    ).one()
    return MovieDetailItemSchema.model_validate(movie).model_copy(
        update={
            "likes": likes,
            "dislikes": dislikes,
            "rating_avg": None if rating_avg is None else round(float(rating_avg), 2),
            "rating_count": rating_count,
        }
    )


def comment_link(movie_id: int, comment_id: int) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/movies/{movie_id}#comment-{comment_id}"
