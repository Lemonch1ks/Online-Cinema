from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator



class GenreSchema(BaseModel):
    id: int
    name: str


class CertificationSchema(BaseModel):
    id: int
    name: str


class StarSchema(BaseModel):
    id: int
    name: str


class DirectorSchema(BaseModel):
    id: int
    name: str



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


class MoviDetailItemSchema(MovieBaseSchema):
    id: int
    uuid: UUID
    meta_score: float | None
    gross: float | None
    price: Decimal
    certification_id: int
    genres: list[GenreSchema]
    directors: list[DirectorSchema]
    stars: list[StarSchema]
