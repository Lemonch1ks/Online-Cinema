from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import stripe
from stripe import StripeClient

CURRENCY = "usd"


class PaymentGatewayError(Exception):
    """The payment provider failed or rejected the request."""


class InvalidWebhookError(Exception):
    """The webhook request is not signed by Stripe or its body is not an event."""


@dataclass(frozen=True)
class CheckoutItem:
    name: str
    price: Decimal


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class WebhookEvent:
    """The part of a Stripe event the app needs. Checkout fields are None for other event types."""

    type: str
    session_id: str | None = None
    order_id: int | None = None
    payment_status: str | None = None
    amount_total: int | None = None
    payment_intent: str | None = None


def to_cents(amount: Decimal) -> int:
    """Stripe takes amounts as whole cents: Decimal("9.99") -> 999."""
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def parse_order_id(value: object) -> int | None:
    return int(value) if isinstance(value, str) and value.isdigit() else None


class StripeGateway:
    def __init__(self, secret_key: str, webhook_secret: str, success_url: str, cancel_url: str) -> None:
        self._client = StripeClient(secret_key)
        self._webhook_secret = webhook_secret
        self._success_url = success_url
        self._cancel_url = cancel_url

    async def create_checkout_session(self, order_id: int, items: list[CheckoutItem]) -> CheckoutSession:
        """Opens a Stripe Checkout page for the order, one line per movie."""
        try:
            session = await self._client.v1.checkout.sessions.create_async(
                params={
                    "mode": "payment",
                    "line_items": [
                        {
                            "price_data": {
                                "currency": CURRENCY,
                                "product_data": {"name": item.name},
                                "unit_amount": to_cents(item.price),
                            },
                            "quantity": 1,
                        }
                        for item in items
                    ],
                    # The webhook finds the order by this value; Stripe keeps metadata values as strings.
                    "metadata": {"order_id": str(order_id)},
                    "success_url": self._success_url,
                    "cancel_url": self._cancel_url,
                }
            )
        except stripe.StripeError as e:
            raise PaymentGatewayError(str(e)) from e

        if session.url is None:
            raise PaymentGatewayError("Stripe returned a checkout session without a payment page url.")
        return CheckoutSession(id=session.id, url=session.url)

    async def get_checkout_status(self, session_id: str) -> str:
        """The payment page status: "open" (not paid yet), "complete" (paid) or "expired"."""
        try:
            session = await self._client.v1.checkout.sessions.retrieve_async(session_id)
        except stripe.StripeError as e:
            raise PaymentGatewayError(str(e)) from e
        return str(session.status)

    async def close_checkout_session(self, session_id: str) -> str:
        """Makes an open payment page unusable. Returns the final status: "expired", or "complete" if already paid."""
        sessions = self._client.v1.checkout.sessions
        try:
            session = await sessions.retrieve_async(session_id)
            if session.status == "open":
                session = await sessions.expire_async(session_id)
        except stripe.StripeError as e:
            raise PaymentGatewayError(str(e)) from e
        return str(session.status)

    async def refund(self, payment_intent: str) -> None:
        """Returns the whole payment to the customer."""
        try:
            await self._client.v1.refunds.create_async(params={"payment_intent": payment_intent})
        except stripe.StripeError as e:
            raise PaymentGatewayError(str(e)) from e

    def parse_event(self, payload: bytes, signature: str | None) -> WebhookEvent:
        """Checks the Stripe-Signature header against the raw body and reads the event."""
        try:
            event = self._client.construct_event(payload, signature, self._webhook_secret)
        except (stripe.SignatureVerificationError, ValueError) as e:
            raise InvalidWebhookError(str(e)) from e

        return read_event(event.type, event.data.object.to_dict())


def read_event(event_type: str, data_object: dict) -> WebhookEvent:
    """Takes the checkout fields out of a Stripe event; other event types keep only their type."""
    if not event_type.startswith("checkout.session."):
        return WebhookEvent(type=event_type)
    return WebhookEvent(
        type=event_type,
        session_id=data_object.get("id"),
        order_id=parse_order_id((data_object.get("metadata") or {}).get("order_id")),
        payment_status=data_object.get("payment_status"),
        amount_total=data_object.get("amount_total"),
        payment_intent=data_object.get("payment_intent"),
    )
