from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, require_role
from src.auth.models import User, UserGroupEnum
from src.cart.models import Cart, CartItem
from src.core.config import settings
from src.core.database import get_db
from src.movies.models import Movie
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import EmailSender
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.schemas import (
    CheckoutResponseSchema,
    ExcludedMovieSchema,
    ExclusionReasonEnum,
    OrderCreatedSchema,
    OrderListResponseSchema,
    OrderSchema,
    OrdersQuery,
)
from src.orders.services import (
    filter_admin_list,
    movie_ids_in_orders,
    newest_first,
    order_schema,
    paginate,
    with_items,
)
from src.payments.dependencies import get_payment_gateway
from src.payments.gateway import CheckoutItem, PaymentGatewayError, StripeGateway
from src.payments.models import Payment, PaymentStatusEnum
from src.payments.services import GATEWAY_UNAVAILABLE, notify

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


ORDER_NOT_FOUND_RESPONSE = {"description": "No such order among the current user's orders."}
GATEWAY_ERROR_RESPONSE = {"description": "Stripe is unavailable or rejected the request; nothing was charged."}


async def get_own_order(db: AsyncSession, user: User, order_id: int) -> Order:
    """The user's order with its items, locked until the end of the transaction; 404 for others' orders."""
    stmt = with_items(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    order = await db.scalar(stmt)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No orders with id:{order_id} found.")
    return order


async def close_checkout(gateway: StripeGateway, order: Order) -> str | None:
    """Expires the order's open payment page, so it cannot be paid after a cancel or a new /pay.

    Returns the final session status ("expired" or "complete"), or None if the order has no payment page.
    """
    if order.checkout_session_id is None:
        return None
    try:
        return await gateway.close_checkout_session(order.checkout_session_id)
    except PaymentGatewayError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GATEWAY_UNAVAILABLE) from None


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderSchema,
    summary="Cancel Order",
    description=(
        "Only a pending order can be canceled; a paid one can only be refunded. "
        "An open Stripe payment page of the order is closed, so it cannot be paid afterwards."
    ),
    responses={
        404: ORDER_NOT_FOUND_RESPONSE,
        409: {"description": "The order is not pending, or it has just been paid and the payment is being confirmed."},
        502: GATEWAY_ERROR_RESPONSE,
    },
)
async def cancel_order(
    order_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    payment_gateway: StripeGateway = Depends(get_payment_gateway),
) -> OrderSchema:
    order = await get_own_order(db, user, order_id)
    if order.status != OrderStatusEnum.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending orders can be canceled.")
    if await close_checkout(payment_gateway, order) == "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The order has just been paid, the payment is being confirmed. Request a refund instead.",
        )

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
    page = await paginate(db, request, filter_admin_list(select(Order), Order, query), query.page, query.per_page)
    orders = [order_schema(order) for order in await db.scalars(with_items(newest_first(page.stmt)))]
    return OrderListResponseSchema(
        orders=orders,
        prev_page=page.prev_page,
        next_page=page.next_page,
        total_pages=page.total_pages,
        total_items=page.total_items,
    )


@router.post(
    "/orders/{order_id}/pay",
    response_model=CheckoutResponseSchema,
    summary="Pay for Order",
    description=(
        "Opens a Stripe Checkout page for a pending order of the current user and returns its url. "
        "Prices are checked first: if a movie price has changed since the order was placed, the order is updated "
        "to the current prices and 409 is returned with the new total, so the user confirms it by paying again. "
        "A payment page opened earlier for the order is closed. "
        "The order becomes paid only after Stripe confirms the payment through the webhook, "
        "not when the user is redirected back."
    ),
    responses={
        404: ORDER_NOT_FOUND_RESPONSE,
        409: {
            "description": (
                "The order is not pending, prices have changed (the order now has the new total), "
                "or the order has just been paid."
            )
        },
        502: GATEWAY_ERROR_RESPONSE,
    },
)
async def order_payment(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    payment_gateway: StripeGateway = Depends(get_payment_gateway),
) -> CheckoutResponseSchema:
    order = await get_own_order(db, user, order_id)
    if order.status != OrderStatusEnum.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending orders can be paid.")

    changed = [item for item in order.items if item.price_at_order != item.movie.price]
    if changed:
        for item in changed:
            item.price_at_order = item.movie.price
        new_total = sum((item.price_at_order for item in order.items), Decimal("0.00"))
        order.total_amount = new_total
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Prices have changed since the order was placed. New total: {new_total}. Pay again to confirm.",
        )

    if await close_checkout(payment_gateway, order) == "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The order has just been paid, the payment is being confirmed.",
        )
    items = [CheckoutItem(name=item.movie.name, price=item.price_at_order) for item in order.items]
    try:
        session = await payment_gateway.create_checkout_session(order_id=order.id, items=items)
    except PaymentGatewayError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GATEWAY_UNAVAILABLE) from None

    order.checkout_session_id = session.id
    await db.commit()
    return CheckoutResponseSchema(checkout_url=session.url)


@router.post(
    "/orders/{order_id}/refund",
    response_model=OrderSchema,
    summary="Refund Order",
    description=(
        "Returns the money for a paid order through Stripe: the payment becomes refunded and the order canceled, "
        "so its movies are no longer purchased. The user gets an email."
    ),
    responses={
        404: ORDER_NOT_FOUND_RESPONSE,
        409: {"description": "The order is not paid."},
        502: GATEWAY_ERROR_RESPONSE,
    },
)
async def refund_order(
    order_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    payment_gateway: StripeGateway = Depends(get_payment_gateway),
    email_sender: EmailSender = Depends(get_email_sender),
) -> OrderSchema:
    order = await get_own_order(db, user, order_id)
    stmt = select(Payment).where(Payment.order_id == order.id, Payment.status == PaymentStatusEnum.successful)
    payment = await db.scalar(stmt.with_for_update())
    if order.status != OrderStatusEnum.paid or payment is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only paid orders can be refunded.")

    try:
        await payment_gateway.refund(payment.external_payment_id)
    except PaymentGatewayError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GATEWAY_UNAVAILABLE) from None

    payment.status = PaymentStatusEnum.refunded
    order.status = OrderStatusEnum.canceled
    await db.commit()
    await notify(email_sender.send_refund_email, user.email, settings.ORDERS_LINK_ENDPOINT)
    return order_schema(order)
