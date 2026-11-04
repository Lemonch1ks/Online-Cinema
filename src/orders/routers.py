from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, require_role
from src.auth.models import User, UserGroupEnum
from src.cart.models import Cart, CartItem
from src.core.database import get_db
from src.movies.models import Movie
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.schemas import (
    ExcludedMovieSchema,
    ExclusionReasonEnum,
    OrderCreatedSchema,
    OrderListResponseSchema,
    OrderSchema,
    OrdersQuery,
)
from src.orders.services import filter_orders, movie_ids_in_orders, newest_first, order_schema, with_items

router = APIRouter()


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderCreatedSchema,
    summary="Place Order",
    description=(
        "Creates a pending order from the current user's cart and clears the cart. "
        "Movies the user has already purchased or that are in their other pending order are left out "
        "and listed in `excluded`."
    ),
    responses={400: {"description": "The cart is empty, or none of its movies can be ordered."}},
)
async def place_order(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderCreatedSchema:
    # Locking the cart row makes two simultaneous orders of the same user wait for each other.
    cart_id = await db.scalar(select(Cart.id).where(Cart.user_id == user.id).with_for_update())
    stmt = (
        select(Movie)
        .join(CartItem, CartItem.movie_id == Movie.id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.added_at, CartItem.id)
    )
    movies = [] if cart_id is None else list(await db.scalars(stmt))
    if not movies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The cart is empty.")

    purchased = await movie_ids_in_orders(db, user.id, OrderStatusEnum.paid)
    pending = await movie_ids_in_orders(db, user.id, OrderStatusEnum.pending)
    ordered: list[Movie] = []
    excluded: list[ExcludedMovieSchema] = []
    for movie in movies:
        if movie.id in purchased:
            excluded.append(
                ExcludedMovieSchema(movie_id=movie.id, name=movie.name, reason=ExclusionReasonEnum.purchased)
            )
        elif movie.id in pending:
            excluded.append(
                ExcludedMovieSchema(movie_id=movie.id, name=movie.name, reason=ExclusionReasonEnum.pending_order)
            )
        else:
            ordered.append(movie)
    if not ordered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="None of the movies in the cart can be ordered."
        )

    order = Order(
        user_id=user.id,
        status=OrderStatusEnum.pending,
        total_amount=sum((movie.price for movie in ordered), Decimal("0.00")),
        items=[OrderItem(movie=movie, price_at_order=movie.price) for movie in ordered],
    )
    db.add(order)
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
    await db.commit()
    await db.refresh(order, ["created_at"])
    return OrderCreatedSchema(**order_schema(order).model_dump(), excluded=excluded)


@router.get(
    "/orders",
    response_model=list[OrderSchema],
    summary="Get My Orders",
    description="The current user's orders, newest first.",
)
async def list_my_orders(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderSchema]:
    stmt = with_items(newest_first(select(Order).where(Order.user_id == user.id)))
    return [order_schema(order) for order in await db.scalars(stmt)]


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderSchema,
    summary="Cancel Order",
    description="Only a pending order can be canceled; a paid one can only be refunded.",
    responses={
        404: {"description": "No such order among the current user's orders."},
        409: {"description": "The order is not pending."},
    },
)
async def cancel_order(
    order_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderSchema:
    stmt = with_items(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    order = await db.scalar(stmt)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No orders with id:{order_id} found.")
    if order.status != OrderStatusEnum.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending orders can be canceled.")

    order.status = OrderStatusEnum.canceled
    await db.commit()
    return order_schema(order)


@router.get(
    "/admins/orders",
    dependencies=[Depends(require_role(UserGroupEnum.ADMIN))],
    response_model=OrderListResponseSchema,
    summary="Get All Orders",
    description="Admins only: orders of all users, newest first, filtered by user, status and dates (UTC, inclusive).",
)
async def list_all_orders(
    request: Request,
    query: Annotated[OrdersQuery, Query()],
    db: AsyncSession = Depends(get_db),
) -> OrderListResponseSchema:
    page, per_page = query.page, query.per_page
    stmt = filter_orders(select(Order), query)

    total_items = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    stmt = with_items(newest_first(stmt)).offset((page - 1) * per_page).limit(per_page)
    orders = [order_schema(order) for order in await db.scalars(stmt)]

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return OrderListResponseSchema(
        orders=orders,
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )
