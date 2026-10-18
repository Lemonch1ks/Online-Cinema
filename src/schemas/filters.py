from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Select

from src.db.models import Movie


class BasePagination(BaseModel):
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(10, ge=1, le=20, description="Number of items per page")


class MovieFilter(BasePagination):
    imdb_from: float | None = Field(None, ge=0, description="Filters from IMDB rating")
    imdb_to: float | None = Field(None, ge=0, description="Filters to IMDB rating")
    meta_score_from: float | None = Field(None, ge=0, description="Filters from meta rating")
    meta_score_to: float | None = Field(None, ge=0, description="Filters to meta rating")
    gross_from: float | None = Field(None, ge=0, description="Filters from gross")
    gross_to: float | None = Field(None, ge=0, description="Filters to gross")
    year_from: int | None = Field(None, ge=0, description="Filters from year")
    year_to: int | None = Field(None, ge=0, description="Filters to year")

    model_config = {"extra": "forbid"}

    def filter(self, stmt: Select) -> Select:
        if self.imdb_from is not None:
            stmt = stmt.where(Movie.imdb >= self.imdb_from)

        if self.imdb_to is not None:
            stmt = stmt.where(Movie.imdb <= self.imdb_to)

        if self.meta_score_from is not None:
            stmt = stmt.where(Movie.meta_score >= self.meta_score_from)

        if self.meta_score_to is not None:
            stmt = stmt.where(Movie.meta_score <= self.meta_score_to)

        if self.year_from is not None:
            stmt = stmt.where(Movie.year >= self.year_from)

        if self.year_to is not None:
            stmt = stmt.where(Movie.year <= self.year_to)

        if self.gross_from is not None:
            stmt = stmt.where(Movie.gross >= self.gross_from)

        if self.gross_to is not None:
            stmt = stmt.where(Movie.gross <= self.gross_to)

        return stmt
