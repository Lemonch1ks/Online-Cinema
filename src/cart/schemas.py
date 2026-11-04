from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class CartItemInSchema(BaseModel):
    movie_id: int

    model_config = {"extra": "forbid"}


class CartItemSchema(BaseModel):
    movie_id: int
    name: str
    price: Decimal
    year: int
    genres: list[str]
    added_at: datetime


class CartSchema(BaseModel):
    items: list[CartItemSchema]
    total_price: Decimal
