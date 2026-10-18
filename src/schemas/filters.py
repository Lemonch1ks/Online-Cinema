from pydantic import BaseModel, Field
from sqlalchemy import Select, desc, asc

from enum import Enum
from src.db.models import Movie


class BasePagination(BaseModel):
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(10, ge=1, le=20, description="Number of items per page")


class MovieFilter(BaseModel):
    imdb_from: float | None = Field(None, ge=0, description="Filters from IMDB rating")
    imdb_to: float | None = Field(None, ge=0, description="Filters to IMDB rating")
    meta_score_from: float | None = Field(None, ge=0, description="Filters from meta rating")
    meta_score_to: float | None = Field(None, ge=0, description="Filters to meta rating")
    gross_from: float | None = Field(None, ge=0, description="Filters from gross")
    gross_to: float | None = Field(None, ge=0, description="Filters to gross")
    year_from: int | None = Field(None, ge=0, description="Filters from year")
    year_to: int | None = Field(None, ge=0, description="Filters to year")


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


class OrderTypeEnum(str, Enum):
    asc = "asc"
    desc = "desc"


class SortByEnum(str, Enum):
    imdb = "imdb"
    meta_score = "meta_score"
    year = "year"
    gross = "gross"


class MovieSort(BaseModel):
    order_type: OrderTypeEnum = Field(OrderTypeEnum.desc, description="Order type")
    sort_by: SortByEnum | None = Field(None, description="Sort by an attribute")


    def sort(self, stmt: Select) -> Select:

        sort_types = {
            SortByEnum.imdb: Movie.imdb,
            SortByEnum.meta_score: Movie.meta_score,
            SortByEnum.year: Movie.year,
            SortByEnum.gross: Movie.gross
        }

        order = {
            OrderTypeEnum.desc: desc,
            OrderTypeEnum.asc: asc
        }

        if self.sort_by is not None:
            return stmt.order_by(order[self.order_type](sort_types.get(self.sort_by)))

        return stmt


class MoviesQuery(
    BasePagination,
    MovieFilter,
    MovieSort,
):
    model_config = {"extra": "forbid"}
