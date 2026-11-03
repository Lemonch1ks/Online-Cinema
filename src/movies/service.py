from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.movies.models import Certification, Director, Genre, Star


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
