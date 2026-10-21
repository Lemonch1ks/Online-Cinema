from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import String, Float, Integer, DECIMAL, ForeignKey, Uuid, UniqueConstraint, Text, Table, Column
from src.core.database import Base
from uuid import UUID, uuid4
from decimal import Decimal


movie_genres_table = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("genre_id", ForeignKey("genres.id"), primary_key=True),
)


movie_directors_table = Table(
    "movie_directors",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("director_id", ForeignKey("directors.id"), primary_key=True),
)

movie_stars_table = Table(
    "movie_stars",
    Base.metadata,
    Column("movie_id", ForeignKey("movies.id"), primary_key=True),
    Column("star_id", ForeignKey("stars.id"), primary_key=True),
)


class Movie(Base):
    __tablename__ = 'movies'
    __table_args__ = (
        UniqueConstraint("name", "year", "time", name="unique_name_time_year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[int] = mapped_column(Integer, nullable=False)
    imdb: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(DECIMAL(10,2), nullable=False)
    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id"), nullable=False)
    certification: Mapped["Certification"] = relationship(back_populates="movies")
    genres: Mapped[list["Genre"]] = relationship(secondary=movie_genres_table, back_populates="movies")
    stars: Mapped[list["Star"]] = relationship(secondary=movie_stars_table, back_populates="movies")
    directors: Mapped[list["Director"]] = relationship(secondary=movie_directors_table, back_populates="movies")

class Certification(Base):
    __tablename__ = 'certifications'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    movies: Mapped[list["Movie"]] = relationship(back_populates="certification")


class Genre(Base):
    __tablename__ = 'genres'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(secondary=movie_genres_table, back_populates="genres")

class Star(Base):
    __tablename__ = 'stars'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(secondary=movie_stars_table, back_populates="stars")


class Director(Base):
    __tablename__ = 'directors'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(secondary=movie_directors_table, back_populates="directors")
