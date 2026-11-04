from datetime import UTC, datetime, time, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.schemas import OrderItemSchema, OrderSchema, OrdersQuery


async def movie_ids_in_orders(db: AsyncSession, user_id: int, status: OrderStatusEnum) -> set[int]:
    """Movies in the user's orders with this status; with `paid` these are the movies the user has purchased."""
    stmt = (
        select(OrderItem.movie_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user_id, Order.status == status)
    )
    return set(await db.scalars(stmt))


async def count_orders_with_movie(db: AsyncSession, movie_id: int) -> int:
    stmt = select(func.count()).select_from(OrderItem).where(OrderItem.movie_id == movie_id)
    return (await db.execute(stmt)).scalar_one()


def with_items(stmt: Select) -> Select:
    return stmt.options(selectinload(Order.items).selectinload(OrderItem.movie))


def order_schema(order: Order) -> OrderSchema:
    return OrderSchema(
        id=order.id,
        user_id=order.user_id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items=[
            OrderItemSchema(movie_id=item.movie_id, name=item.movie.name, price_at_order=item.price_at_order)
            for item in order.items
        ],
    )


def newest_first(stmt: Select) -> Select:
    return stmt.order_by(Order.created_at.desc(), Order.id.desc())


def filter_orders(stmt: Select, query: OrdersQuery) -> Select:
    if query.user_id is not None:
        stmt = stmt.where(Order.user_id == query.user_id)
    if query.status is not None:
        stmt = stmt.where(Order.status == query.status)
    if query.date_from is not None:
        stmt = stmt.where(Order.created_at >= datetime.combine(query.date_from, time.min, UTC))
    if query.date_to is not None:
        stmt = stmt.where(Order.created_at < datetime.combine(query.date_to + timedelta(days=1), time.min, UTC))
    return stmt
