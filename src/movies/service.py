from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.movies.models import Certification, Director, Genre, Movie, Star


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
