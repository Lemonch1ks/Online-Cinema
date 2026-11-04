import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.models import User
from src.core.config import settings
from src.notifications.emails import BaseEmailError, EmailSender
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.orders.services import with_items
from src.payments.gateway import StripeGateway, WebhookEvent, from_cents, to_cents
from src.payments.models import Payment, PaymentItem, PaymentStatusEnum
from src.payments.schemas import PaymentItemSchema, PaymentSchema

logger = logging.getLogger(__name__)

GATEWAY_UNAVAILABLE = "Payment provider is unavailable, try again later."
TRY_ANOTHER_METHOD = "The payment was not completed. Try a different payment method."

# A checkout page was paid; async methods (bank debits) report success later with their own event.
PAID_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
# The page was not paid in time, or a delayed payment was declined: the order stays pending.
FAILED_EVENTS = {"checkout.session.expired", "checkout.session.async_payment_failed"}


async def notify(send: Callable[[str, str], Awaitable[None]], email: str, link: str) -> None:
    """Sends an email without failing the request: the payment is already recorded either way."""
    try:
        await send(email, link)
    except BaseEmailError:
        logger.exception("Failed to send a payment email to %s", email)


def with_payment_items(stmt: Select) -> Select:
    return stmt.options(selectinload(Payment.items).selectinload(PaymentItem.order_item).selectinload(OrderItem.movie))


def payment_schema(payment: Payment) -> PaymentSchema:
    return PaymentSchema(
        id=payment.id,
        user_id=payment.user_id,
        order_id=payment.order_id,
        created_at=payment.created_at,
        status=payment.status,
        amount=payment.amount,
        items=[
            PaymentItemSchema(
                movie_id=item.order_item.movie_id,
                name=item.order_item.movie.name,
                price_at_payment=item.price_at_payment,
            )
            for item in payment.items
        ],
    )


async def payment_exists(db: AsyncSession, external_payment_id: str) -> bool:
    stmt = select(Payment.id).where(Payment.external_payment_id == external_payment_id)
    return await db.scalar(stmt) is not None


async def handle_event(
    db: AsyncSession, gateway: StripeGateway, email_sender: EmailSender, event: WebhookEvent
) -> None:
    if event.type in PAID_EVENTS:
        await record_payment(db, gateway, email_sender, event)
    elif event.type in FAILED_EVENTS:
        await report_failed_payment(db, email_sender, event)


async def record_payment(
    db: AsyncSession, gateway: StripeGateway, email_sender: EmailSender, event: WebhookEvent
) -> None:
    """Saves the money Stripe received and marks the order paid.

    Stripe may send the same event again: a payment that is already saved is not saved twice.
    Money that came for an order that can no longer be paid (canceled, already paid, another total) is returned.
    """
    if event.payment_status != "paid" or event.payment_intent is None or event.amount_total is None:
        return  # a delayed payment method: async_payment_succeeded comes when the money arrives
    if event.order_id is None:
        logger.error("Stripe payment %s has no order_id in metadata", event.payment_intent)
        return
    order = await db.scalar(with_items(select(Order).where(Order.id == event.order_id).with_for_update()))
    if order is None:
        logger.error("Stripe payment %s is for an unknown order %s", event.payment_intent, event.order_id)
        return
    # Checked after the order lock: a copy of the event processed at the same moment has committed by now,
    # so it is seen as saved here instead of looking like a second payment for a paid order (and refunded).
    if await payment_exists(db, event.payment_intent):
        return

    accepted = order.status == OrderStatusEnum.pending and event.amount_total == to_cents(order.total_amount)
    if not accepted:
        logger.warning("Refunding Stripe payment %s: order %s cannot take it", event.payment_intent, order.id)
        await gateway.refund(event.payment_intent)  # PaymentGatewayError -> 502, Stripe sends the event again
    db.add(
        Payment(
            user_id=order.user_id,
            order_id=order.id,
            status=PaymentStatusEnum.successful if accepted else PaymentStatusEnum.refunded,
            amount=from_cents(event.amount_total),
            external_payment_id=event.payment_intent,
            items=[PaymentItem(order_item_id=item.id, price_at_payment=item.price_at_order) for item in order.items],
        )
    )
    if accepted:
        order.status = OrderStatusEnum.paid
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()  # the same event processed at the same moment by another request
        return

    email = (await db.execute(select(User.email).where(User.id == order.user_id))).scalar_one()
    if accepted:
        await notify(email_sender.send_payment_success_email, email, settings.PURCHASES_LINK_ENDPOINT)
    else:
        await notify(email_sender.send_refund_email, email, settings.ORDERS_LINK_ENDPOINT)


async def report_failed_payment(db: AsyncSession, email_sender: EmailSender, event: WebhookEvent) -> None:
    """Suggests another payment method when the current payment page of a pending order failed or expired.

    Pages the app closed itself (the order was canceled or a new page was opened) are not reported.
    """
    if event.session_id is None:
        return
    order = await db.scalar(select(Order).where(Order.checkout_session_id == event.session_id))
    if order is None or order.status != OrderStatusEnum.pending:
        return
    email = (await db.execute(select(User.email).where(User.id == order.user_id))).scalar_one()
    await notify(email_sender.send_payment_failed_email, email, settings.ORDERS_LINK_ENDPOINT)
