from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DECIMAL,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base

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
    __tablename__ = "movies"
    __table_args__ = (UniqueConstraint("name", "year", "time", name="unique_name_time_year"),)
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
    price: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    certification_id: Mapped[int] = mapped_column(ForeignKey("certifications.id"), nullable=False)
    certification: Mapped["Certification"] = relationship(back_populates="movies")
    genres: Mapped[list["Genre"]] = relationship(secondary=movie_genres_table, back_populates="movies")
    stars: Mapped[list["Star"]] = relationship(secondary=movie_stars_table, back_populates="movies")
    directors: Mapped[list["Director"]] = relationship(secondary=movie_directors_table, back_populates="movies")


class Certification(Base):
    __tablename__ = "certifications"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    movies: Mapped[list["Movie"]] = relationship(back_populates="certification")


class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(
        secondary=movie_genres_table, back_populates="genres", order_by="Movie.id"
    )


class Star(Base):
    __tablename__ = "stars"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(
        secondary=movie_stars_table, back_populates="stars", order_by="Movie.id"
    )


class Director(Base):
    __tablename__ = "directors"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    movies: Mapped[list["Movie"]] = relationship(
        secondary=movie_directors_table, back_populates="directors", order_by="Movie.id"
    )


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (Index("ix_favorites_movie_id", "movie_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MovieReaction(Base):
    """A like (is_like=True) or a dislike (is_like=False); the primary key allows only one per user and movie."""

    __tablename__ = "movie_reactions"
    __table_args__ = (Index("ix_movie_reactions_movie_id", "movie_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    is_like: Mapped[bool] = mapped_column(Boolean, nullable=False)


class MovieRating(Base):
    __tablename__ = "movie_ratings"
    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 10", name="movie_ratings_score_range"),
        Index("ix_movie_ratings_movie_id", "movie_id"),
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Comment(Base):
    """A comment on a movie; a reply has parent_id of a top-level comment (only one level of replies)."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_movie_id_parent_id", "movie_id", "parent_id"),
        Index("ix_comments_parent_id", "parent_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CommentLike(Base):
    __tablename__ = "comment_likes"
    __table_args__ = (Index("ix_comment_likes_comment_id", "comment_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True)
