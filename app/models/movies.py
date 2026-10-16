"""ORM-модели каталога фильмов (раздел "2. Movies" в README).

Mapped[...] + mapped_column() — современный (SQLAlchemy 2.x) способ описывать
колонки: тип Python в аннотации сам задаёт nullable (Optional → NULL разрешён).
"""

import uuid as uuid_lib
from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Numeric, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Связующие таблицы many-to-many. У них нет своей модели: это просто пары id.
movie_genres = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)

movie_directors = Table(
    "movie_directors",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("director_id", ForeignKey("directors.id", ondelete="CASCADE"), primary_key=True),
)

movie_stars = Table(
    "movie_stars",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True),
    Column("star_id", ForeignKey("stars.id", ondelete="CASCADE"), primary_key=True),
)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    # secondary= говорит SQLAlchemy, через какую таблицу идёт связь
    movies: Mapped[list["Movie"]] = relationship(secondary=movie_genres, back_populates="genres")


class Star(Base):
    __tablename__ = "stars"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)

    movies: Mapped[list["Movie"]] = relationship(secondary=movie_stars, back_populates="stars")


class Director(Base):
    __tablename__ = "directors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)

    movies: Mapped[list["Movie"]] = relationship(secondary=movie_directors, back_populates="directors")


class Certification(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

    # one-to-many: у одного рейтинга (PG-13) много фильмов
    movies: Mapped[list["Movie"]] = relationship(back_populates="certification")


class Movie(Base):
    __tablename__ = "movies"
    # Фильм однозначно определяется сочетанием названия, года и длительности
    __table_args__ = (UniqueConstraint("name", "year", "time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(unique=True, default=uuid_lib.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    year: Mapped[int]
    time: Mapped[int]  # длительность в минутах
    imdb: Mapped[float]
    votes: Mapped[int]
    meta_score: Mapped[float | None]
    gross: Mapped[float | None]
    description: Mapped[str] = mapped_column(Text)
    # Numeric (DECIMAL) вместо float: деньги нельзя хранить с ошибками округления
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id"))

    certification: Mapped[Certification] = relationship(back_populates="movies")
    genres: Mapped[list[Genre]] = relationship(secondary=movie_genres, back_populates="movies")
    directors: Mapped[list[Director]] = relationship(secondary=movie_directors, back_populates="movies")
    stars: Mapped[list[Star]] = relationship(secondary=movie_stars, back_populates="movies")
