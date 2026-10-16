from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from db.models.movies import Certification, Genre, Director, Star


class MovieBaseSchema(BaseModel):
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    price: Decimal
    certification_id: int
    certification: Certification
    genres: list[Genre]
    directors: list[Director]
    stars: list[Star]

class MovieListItemSchema(BaseModel):
    id: int
    name: str
    year: int
    time: int
    meta_score: float | None = None


class MovieListResponseSchema(BaseModel):
    movies: List[MovieListItemSchema]
    next_page: Optional[str]
    prev_page: Optional[str]
    total_pages: int
    total_items: int

    model_config = {
        "from_attributes": True,
    }


class MoviDetailsSchema(BaseModel):
    id: int
    uuid: str
    name: str
    year: int
    time: int
    imdb: float
    votes: int
    meta_score: float | None
    gross: float | None
    description: str
    price: Decimal
    certification_id: int
    certification: Certification
    genres: list[Genre]
    directors: list[Director]
    stars: list[Star]
