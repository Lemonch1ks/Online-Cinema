"""Эндпоинты каталога: список фильмов, один фильм, жанры.

APIRouter — "кусок" приложения со своими маршрутами; в main.py он подключается
через app.include_router(). Так эндпоинты разных разделов живут в разных файлах.
"""

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Genre, Movie, movie_genres
from app.schemas.movies import GenreWithCount, MovieDetail, MoviePage

router = APIRouter(tags=["movies"])

# Annotated + Depends: FastAPI сам вызовет get_db и передаст сессию в функцию
DbSession = Annotated[Session, Depends(get_db)]


class SortField(StrEnum):
    # Enum в параметре запроса = в /docs появится выпадающий список,
    # а неверное значение FastAPI отклонит с ошибкой 422
    name = "name"
    year = "year"
    imdb = "imdb"
    price = "price"
    votes = "votes"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


@router.get("/movies", response_model=MoviePage)
def list_movies(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
    year: int | None = None,
    min_imdb: Annotated[float | None, Query(ge=0, le=10)] = None,
    genre_id: int | None = None,
    search: Annotated[str | None, Query(description="Поиск по названию и описанию")] = None,
    sort_by: SortField = SortField.imdb,
    order: SortOrder = SortOrder.desc,
):
    # Собираем запрос по шагам: каждый фильтр добавляется, только если передан
    query = select(Movie)
    if year is not None:
        query = query.where(Movie.year == year)
    if min_imdb is not None:
        query = query.where(Movie.imdb >= min_imdb)
    if genre_id is not None:
        query = query.where(Movie.genres.any(Genre.id == genre_id))
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Movie.name.ilike(pattern), Movie.description.ilike(pattern)))

    # Сначала считаем общее количество (для пагинации), потом берём одну страницу
    total = db.scalar(select(func.count()).select_from(query.subquery()))

    sort_column = getattr(Movie, sort_by.value)
    # Movie.id вторым ключом: при равных значениях порядок стабилен между страницами
    query = query.order_by(
        sort_column.desc() if order == SortOrder.desc else sort_column.asc(), Movie.id
    )
    query = query.offset((page - 1) * per_page).limit(per_page)
    # selectinload заранее подгружает жанры одним доп. запросом (иначе N+1 запросов)
    query = query.options(selectinload(Movie.genres))

    movies = db.scalars(query).all()
    return MoviePage(items=movies, total=total, page=page, per_page=per_page)


@router.get("/movies/{movie_id}", response_model=MovieDetail)
def get_movie(movie_id: int, db: DbSession):
    query = (
        select(Movie)
        .where(Movie.id == movie_id)
        .options(
            selectinload(Movie.genres),
            selectinload(Movie.directors),
            selectinload(Movie.stars),
            selectinload(Movie.certification),
        )
    )
    movie = db.scalar(query)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


@router.get("/genres", response_model=list[GenreWithCount])
def list_genres(db: DbSession):
    # LEFT JOIN, чтобы жанры без фильмов тоже попали в список (с количеством 0)
    query = (
        select(Genre.id, Genre.name, func.count(movie_genres.c.movie_id).label("movies_count"))
        .outerjoin(movie_genres, Genre.id == movie_genres.c.genre_id)
        .group_by(Genre.id, Genre.name)
        .order_by(Genre.name)
    )
    return [GenreWithCount(**row._mapping) for row in db.execute(query)]
