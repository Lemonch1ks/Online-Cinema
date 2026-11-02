from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SideSchema(BaseModel):
    id: int
    name: str
    model_config = {
        "from_attributes": True,
    }


class GenreSchema(SideSchema):
    pass


class CertificationSchema(SideSchema):
    pass


class StarSchema(SideSchema):
    pass


class DirectorSchema(SideSchema):
    pass


class MovieBaseSchema(BaseModel):
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    description: str

    model_config = {
        "from_attributes": True,
    }


class MovieListItemSchema(MovieBaseSchema):
    id: int


class MovieListResponseSchema(BaseModel):
    movies: list[MovieListItemSchema]
    next_page: str | None
    prev_page: str | None
    total_pages: int
    total_items: int


class MovieDetailItemSchema(MovieBaseSchema):
    id: int
    uuid: UUID
    meta_score: float | None
    gross: float | None
    price: Decimal
    certification_id: int
    genres: list[GenreSchema]
    directors: list[DirectorSchema]
    stars: list[StarSchema]


class GenreItemSchema(BaseModel):
    id: int
    name: str
    movies_count: int


class GenreListResponseSchema(BaseModel):
    genres: list[GenreItemSchema]


class GenreDetailItemSchema(BaseModel):
    id: int
    name: str
    movies: list[MovieListItemSchema]

    model_config = {"from_attributes": True}
