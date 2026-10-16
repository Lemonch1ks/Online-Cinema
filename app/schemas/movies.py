"""Pydantic-схемы: описывают, какой JSON API отдаёт наружу.

Модель SQLAlchemy (app/models) — как данные лежат в БД.
Схема Pydantic (здесь) — как данные выглядят в ответе API.
from_attributes=True позволяет собрать схему прямо из ORM-объекта.
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class NamedItem(BaseModel):
    """Общая форма для жанра, актёра, режиссёра и рейтинга: id + имя."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class GenreWithCount(NamedItem):
    movies_count: int


class MovieListItem(BaseModel):
    """Короткая карточка фильма для списка."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    year: int
    time: int
    imdb: float
    price: Decimal
    genres: list[NamedItem]


class MovieDetail(MovieListItem):
    """Полная информация о фильме."""

    uuid: uuid.UUID
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    certification: NamedItem
    directors: list[NamedItem]
    stars: list[NamedItem]


class MoviePage(BaseModel):
    """Одна страница списка фильмов + данные для пагинации."""

    items: list[MovieListItem]
    total: int
    page: int
    per_page: int
