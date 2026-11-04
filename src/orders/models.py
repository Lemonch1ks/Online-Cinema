from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.movies.models import Movie


class OrderStatusEnum(str, Enum):
    pending = "pending"
    paid = "paid"
    canceled = "canceled"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_id_created_at", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[OrderStatusEnum] = mapped_column(
        SQLEnum(OrderStatusEnum), nullable=False, default=OrderStatusEnum.pending
    )
    total_amount: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.id", cascade="all, delete-orphan", passive_deletes=True
    )


class OrderItem(Base):
    """A movie in an order with its price at the moment the order was placed.

    A movie that is in any order cannot be deleted (RESTRICT): the order history must stay complete.
    """

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "movie_id", name="uq_order_items_order_id_movie_id"),
        Index("ix_order_items_movie_id", "movie_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    price_at_order: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")
    movie: Mapped[Movie] = relationship()
