from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, require_role
from src.auth.models import User, UserGroupEnum
from src.core.database import get_db
from src.movies.models import Movie
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import EmailSender
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.services import filter_admin_list, paginate
from src.payments.dependencies import get_payment_gateway
from src.payments.gateway import InvalidWebhookError, PaymentGatewayError, StripeGateway
from src.payments.models import Payment, PaymentItem, PaymentStatusEnum
from src.payments.schemas import (
    CheckoutResultEnum,
    CheckoutStatusSchema,
    PaymentListResponseSchema,
    PaymentSchema,
    PaymentsQuery,
    PurchasedMovieSchema,
    WebhookResponseSchema,
)
from src.payments.services import (
    GATEWAY_UNAVAILABLE,
    TRY_ANOTHER_METHOD,
    handle_event,
    payment_schema,
    with_payment_items,
)

router = APIRouter()


def newest_payments_first(stmt):
    return stmt.order_by(Payment.created_at.desc(), Payment.id.desc())


@router.post(
    "/payments/webhook",
    response_model=WebhookResponseSchema,
    summary="Stripe Webhook",
    description=(
        "Called by Stripe, not by users: the request must carry a valid `Stripe-Signature` header. "
        "A paid checkout saves the payment, marks the order paid and emails the user; "
        "a declined or expired checkout emails a suggestion to try a different payment method. "
        "Repeated events change nothing, other event types are accepted and ignored."
    ),
    responses={
        400: {"description": "The signature does not match the body, or the body is not a Stripe event."},
        502: {
            "description": "A refund for a payment that cannot be accepted failed; Stripe will send the event again."
        },
    },
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
    payment_gateway: StripeGateway = Depends(get_payment_gateway),
    email_sender: EmailSender = Depends(get_email_sender),
) -> WebhookResponseSchema:
    # The signature is computed over the raw bytes, so the body is not parsed by FastAPI.
    payload = await request.body()
    try:
        event = payment_gateway.parse_event(payload, stripe_signature)
    except InvalidWebhookError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature or payload."
        ) from None
    try:
        await handle_event(db, payment_gateway, email_sender, event)
    except PaymentGatewayError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GATEWAY_UNAVAILABLE) from None
    return WebhookResponseSchema()


@router.get(
    "/payments/checkout/{session_id}",
    response_model=CheckoutStatusSchema,
    summary="Get Checkout Result",
    description=(
        "For the page Stripe redirects to after the payment page (`session_id` from the redirect url): "
        "whether the order is paid, the payment is still being confirmed, or it failed — "
        "then the message suggests trying a different payment method."
    ),
    responses={
        404: {"description": "No order of the current user has this payment page."},
        502: {"description": "Stripe is unavailable, try again later."},
    },
)
async def get_checkout_result(
    session_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    payment_gateway: StripeGateway = Depends(get_payment_gateway),
) -> CheckoutStatusSchema:
    stmt = select(Order).where(Order.checkout_session_id == session_id, Order.user_id == user.id)
    order = await db.scalar(stmt)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No order with this payment page found.")

    if order.status == OrderStatusEnum.paid:
        result, message = CheckoutResultEnum.paid, "Payment successful. The movies are in your purchases."
    elif order.status == OrderStatusEnum.canceled:
        result, message = CheckoutResultEnum.canceled, "The order is canceled."
    else:
        try:
            checkout_status = await payment_gateway.get_checkout_status(session_id)
        except PaymentGatewayError:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GATEWAY_UNAVAILABLE) from None
        if checkout_status == "complete":
            result = CheckoutResultEnum.processing
            message = "The payment is being confirmed. You will get an email when it is done."
        else:
            result, message = CheckoutResultEnum.not_completed, TRY_ANOTHER_METHOD
    return CheckoutStatusSchema(order_id=order.id, order_status=order.status, result=result, message=message)


@router.get(
    "/payments",
    response_model=list[PaymentSchema],
    summary="Get My Payments",
    description="The current user's payments, newest first: date, amount, status and the movies paid for.",
)
async def list_my_payments(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentSchema]:
    stmt = with_payment_items(newest_payments_first(select(Payment).where(Payment.user_id == user.id)))
    return [payment_schema(payment) for payment in await db.scalars(stmt)]


@router.get(
    "/admins/payments",
    dependencies=[Depends(require_role(UserGroupEnum.ADMIN))],
    response_model=PaymentListResponseSchema,
    summary="Get All Payments",
    description="Admins only: payments of all users, newest first, filtered by user, status and dates (UTC).",
)
async def list_all_payments(
    request: Request,
    query: Annotated[PaymentsQuery, Query()],
    db: AsyncSession = Depends(get_db),
) -> PaymentListResponseSchema:
    stmt = filter_admin_list(select(Payment), Payment, query)
    page = await paginate(db, request, stmt, query.page, query.per_page)
    payments = [
        payment_schema(payment) for payment in await db.scalars(with_payment_items(newest_payments_first(page.stmt)))
    ]
    return PaymentListResponseSchema(
        payments=payments,
        prev_page=page.prev_page,
        next_page=page.next_page,
        total_pages=page.total_pages,
        total_items=page.total_items,
    )


@router.get(
    "/purchases",
    response_model=list[PurchasedMovieSchema],
    summary="Get My Purchased Movies",
    description="Movies the current user has paid for (refunded ones are not included), newest purchase first.",
)
async def list_purchases(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[PurchasedMovieSchema]:
    stmt = (
        select(Movie, PaymentItem.price_at_payment, Payment.created_at)
        .join(OrderItem, OrderItem.movie_id == Movie.id)
        .join(PaymentItem, PaymentItem.order_item_id == OrderItem.id)
        .join(Payment, Payment.id == PaymentItem.payment_id)
        .where(Payment.user_id == user.id, Payment.status == PaymentStatusEnum.successful)
        .order_by(Payment.created_at.desc(), Movie.name)
    )
    return [
        PurchasedMovieSchema(
            movie_id=movie.id, name=movie.name, year=movie.year, price_paid=price, purchased_at=paid_at
        )
        for movie, price, paid_at in await db.execute(stmt)
    ]
