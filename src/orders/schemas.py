from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from src.movies.filters import BasePagination
from src.orders.models import OrderStatusEnum


class OrderItemSchema(BaseModel):
    movie_id: int
    name: str
    price_at_order: Decimal


class OrderSchema(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    status: OrderStatusEnum
    total_amount: Decimal
    items: list[OrderItemSchema]


class ExclusionReasonEnum(str, Enum):
    purchased = "purchased"
    pending_order = "pending_order"


class ExcludedMovieSchema(BaseModel):
    movie_id: int
    name: str
    reason: ExclusionReasonEnum


class OrderCreatedSchema(OrderSchema):
    excluded: list[ExcludedMovieSchema]


class OrderListResponseSchema(BaseModel):
    orders: list[OrderSchema]
    next_page: str | None
    prev_page: str | None
    total_pages: int
    total_items: int


class AdminListQuery(BasePagination):
    """Filters shared by the admin lists of orders and payments."""

    user_id: int | None = Field(None, description="Records of this user only")
    date_from: date | None = Field(None, description="Created on this day (UTC) or later")
    date_to: date | None = Field(None, description="Created on this day (UTC) or earlier")

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise ValueError("date_from must not be later than date_to")
        return self


class OrdersQuery(AdminListQuery):
    status: OrderStatusEnum | None = Field(None, description="Orders with this status only")


class CheckoutResponseSchema(BaseModel):
    checkout_url: str = Field(description="Stripe Checkout page; open it to pay for the order")
