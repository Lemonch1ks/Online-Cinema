from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from src.orders.models import OrderStatusEnum
from src.orders.schemas import AdminListQuery
from src.payments.models import PaymentStatusEnum


class PaymentItemSchema(BaseModel):
    movie_id: int
    name: str
    price_at_payment: Decimal


class PaymentSchema(BaseModel):
    id: int
    user_id: int
    order_id: int
    created_at: datetime
    status: PaymentStatusEnum
    amount: Decimal
    items: list[PaymentItemSchema]


class PaymentListResponseSchema(BaseModel):
    payments: list[PaymentSchema]
    next_page: str | None
    prev_page: str | None
    total_pages: int
    total_items: int


class PaymentsQuery(AdminListQuery):
    status: PaymentStatusEnum | None = Field(None, description="Payments with this status only")


class PurchasedMovieSchema(BaseModel):
    movie_id: int
    name: str
    year: int
    price_paid: Decimal
    purchased_at: datetime


class CheckoutResultEnum(str, Enum):
    paid = "paid"
    processing = "processing"
    not_completed = "not_completed"
    canceled = "canceled"


class CheckoutStatusSchema(BaseModel):
    order_id: int
    order_status: OrderStatusEnum
    result: CheckoutResultEnum
    message: str = Field(description="Text to show the user on the page Stripe redirects to")


class WebhookResponseSchema(BaseModel):
    received: bool = True
