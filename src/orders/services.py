from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.schemas import AdminListQuery, OrderItemSchema, OrderSchema


@dataclass(frozen=True)
class Page:
    stmt: Select
    prev_page: str | None
    next_page: str | None
    total_pages: int
    total_items: int


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


def filter_admin_list(stmt: Select, model: Any, query: AdminListQuery) -> Select:
    """Applies user, status and date filters to a select of orders or payments (both have these columns)."""
    if query.user_id is not None:
        stmt = stmt.where(model.user_id == query.user_id)
    status = getattr(query, "status", None)
    if status is not None:
        stmt = stmt.where(model.status == status)
    if query.date_from is not None:
        stmt = stmt.where(model.created_at >= datetime.combine(query.date_from, time.min, UTC))
    if query.date_to is not None:
        stmt = stmt.where(model.created_at < datetime.combine(query.date_to + timedelta(days=1), time.min, UTC))
    return stmt


async def paginate(db: AsyncSession, request: Request, stmt: Select, page: int, per_page: int) -> Page:
    """Counts the rows of stmt and builds the prev/next links that keep the other query parameters."""
    total_items = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return Page(
        stmt=stmt.offset((page - 1) * per_page).limit(per_page),
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )
