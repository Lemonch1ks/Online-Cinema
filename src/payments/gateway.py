from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import stripe
from stripe import StripeClient

CURRENCY = "usd"


class PaymentGatewayError(Exception):
    """The payment provider failed or rejected the request."""


@dataclass(frozen=True)
class CheckoutItem:
    name: str
    price: Decimal


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


def to_cents(amount: Decimal) -> int:
    """Stripe takes amounts as whole cents: Decimal("9.99") -> 999."""
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


class StripeGateway:
    def __init__(self, secret_key: str, success_url: str, cancel_url: str) -> None:
        self._client = StripeClient(secret_key)
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
