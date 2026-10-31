from pydantic import BaseModel, Field
from sqlalchemy import Select, desc, asc

from enum import Enum

from sqlalchemy.sql import or_


from src.core.config import settings
from src.movies.models import Movie, Star, Director


class BasePagination(BaseModel):
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(
        settings.PAGINATION_DEFAULT_PER_PAGE,
        ge=1,
        le=settings.PAGINATION_MAX_PER_PAGE,
        description="Number of items per page",
    )


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


class MovieSearch(BaseModel):
    search_param: str | None = Field(None, min_length=1, description="Search term")

    model_config = {"str_strip_whitespace": True}

    def search(self, stmt: Select) -> Select:
        if self.search_param is not None:
            stmt = stmt.where(
                or_(
                    Movie.name.icontains(self.search_param, autoescape=True),
                    Movie.description.icontains(self.search_param, autoescape=True),
                    Movie.stars.any(Star.name.icontains(self.search_param, autoescape=True)),
                    Movie.directors.any(Director.name.icontains(self.search_param, autoescape=True)),
                )
            )

        return stmt


class MoviesQuery(
    BasePagination,
    MovieFilter,
    MovieSort,
    MovieSearch,
):
    model_config = {"extra": "forbid"}
