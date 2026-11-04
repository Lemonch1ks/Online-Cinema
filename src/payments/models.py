from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DECIMAL, DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.orders.models import OrderItem


class PaymentStatusEnum(str, Enum):
    successful = "successful"
    canceled = "canceled"
    refunded = "refunded"


class Payment(Base):
    """Money received from Stripe for an order. Created by the webhook once Stripe confirms the payment."""

    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[PaymentStatusEnum] = mapped_column(
        SQLEnum(PaymentStatusEnum), nullable=False, default=PaymentStatusEnum.successful
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    # Unique: Stripe may deliver the same event twice, the second one must not create another payment.
    external_payment_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    items: Mapped[list["PaymentItem"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", passive_deletes=True, order_by="PaymentItem.id"
    )


class PaymentItem(Base):
    """An order item covered by a payment, with the price actually paid for it."""

    __tablename__ = "payment_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price_at_payment: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    payment: Mapped[Payment] = relationship(back_populates="items")
    order_item: Mapped[OrderItem] = relationship()
