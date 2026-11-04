from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StrictBool, StringConstraints, model_validator


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
    likes: int = 0
    dislikes: int = 0
    rating_avg: float | None = None
    rating_count: int = 0


def unique_names(names: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for name in names:
        unique.setdefault(name.lower(), name)
    return list(unique.values())


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Names = Annotated[list[Name], AfterValidator(unique_names)]
Year = Annotated[int, Field(ge=1800, le=2100)]
Minutes = Annotated[int, Field(gt=0)]
Imdb = Annotated[float, Field(ge=0, le=10)]
Votes = Annotated[int, Field(ge=0)]
MetaScore = Annotated[float, Field(ge=0, le=100)]
Gross = Annotated[float, Field(ge=0)]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MovieCreationSchema(BaseModel):
    name: Name
    year: Year
    time: Minutes
    imdb: Imdb
    votes: Votes
    meta_score: MetaScore | None = None
    gross: Gross | None = None
    price: Price
    description: Description
    certification: Name
    genres: Names = []
    stars: Names = []
    directors: Names = []

    model_config = {"extra": "forbid"}


class MovieUpdateSchema(BaseModel):
    name: Name | None = None
    year: Year | None = None
    time: Minutes | None = None
    imdb: Imdb | None = None
    votes: Votes | None = None
    meta_score: MetaScore | None = None
    gross: Gross | None = None
    price: Price | None = None
    description: Description | None = None
    certification: Name | None = None
    genres: Names | None = None
    stars: Names | None = None
    directors: Names | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def forbid_null_for_required_fields(self) -> Self:
        nullable = {"meta_score", "gross"}
        nulls = sorted(name for name in self.model_fields_set - nullable if getattr(self, name) is None)
        if nulls:
            raise ValueError(f"Fields cannot be null: {', '.join(nulls)}")
        return self


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


class NameInSchema(BaseModel):
    name: Name

    model_config = {"extra": "forbid"}


class NamedItemSchema(BaseModel):
    id: int
    name: str
    movies_count: int


class PageSchema(BaseModel):
    next_page: str | None
    prev_page: str | None
    total_pages: int
    total_items: int


class StarListResponseSchema(PageSchema):
    stars: list[NamedItemSchema]


class DirectorListResponseSchema(PageSchema):
    directors: list[NamedItemSchema]


class StarDetailSchema(GenreDetailItemSchema):
    pass


class DirectorDetailSchema(GenreDetailItemSchema):
    pass


class FavoriteSchema(BaseModel):
    movie_id: int


class ReactionInSchema(BaseModel):
    is_like: StrictBool

    model_config = {"extra": "forbid"}


class ReactionSchema(BaseModel):
    movie_id: int
    is_like: bool


class RatingInSchema(BaseModel):
    score: int = Field(ge=1, le=10)

    model_config = {"extra": "forbid"}


class RatingSchema(BaseModel):
    movie_id: int
    score: int


CommentText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CommentInSchema(BaseModel):
    text: CommentText
    parent_id: int | None = None

    model_config = {"extra": "forbid"}


class CommentSchema(BaseModel):
    id: int
    movie_id: int
    author_id: int
    parent_id: int | None
    text: str
    created_at: datetime
    likes_count: int


class CommentWithRepliesSchema(CommentSchema):
    replies: list[CommentSchema]


class CommentListResponseSchema(PageSchema):
    comments: list[CommentWithRepliesSchema]
