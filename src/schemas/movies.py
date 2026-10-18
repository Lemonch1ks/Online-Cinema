from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


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
    movies: List[MovieListItemSchema]
    next_page: Optional[str]
    prev_page: Optional[str]
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
