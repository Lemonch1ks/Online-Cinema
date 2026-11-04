"""StripeGateway without the network: the Stripe API call is replaced, the rest of the gateway is real."""

from decimal import Decimal

import pytest
import stripe

from src.core.config import settings
from src.payments.dependencies import get_payment_gateway
from src.payments.gateway import CheckoutItem, CheckoutSession, PaymentGatewayError, StripeGateway, to_cents

SUCCESS_URL = "http://test/success?session_id={CHECKOUT_SESSION_ID}"
CANCEL_URL = "http://test/cancel"


@pytest.fixture()
def gateway() -> StripeGateway:
    return StripeGateway("sk_test_x", SUCCESS_URL, CANCEL_URL)


def replace_stripe_call(monkeypatch, gateway: StripeGateway, result=None, error: Exception | None = None) -> list:
    """Replaces the Stripe API call; returns the list of params it was called with."""
    calls = []

    async def create_async(params):
        calls.append(params)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(gateway._client.v1.checkout.sessions, "create_async", create_async)
    return calls


def stripe_session(url: str | None) -> stripe.checkout.Session:
    return stripe.checkout.Session.construct_from({"id": "cs_test_1", "url": url}, "sk_test_x")


@pytest.mark.parametrize(
    ("amount", "cents"), [(Decimal("9.99"), 999), (Decimal("0.29"), 29), (Decimal("10"), 1000), (Decimal("0.01"), 1)]
)
def test_to_cents(amount, cents):
    assert to_cents(amount) == cents


async def test_checkout_session_has_a_line_per_movie_and_the_order_id(monkeypatch, gateway):
    calls = replace_stripe_call(monkeypatch, gateway, result=stripe_session("https://checkout.stripe.com/c/pay/1"))

    session = await gateway.create_checkout_session(
        order_id=5, items=[CheckoutItem("The Matrix", Decimal("9.99")), CheckoutItem("Inception", Decimal("7.49"))]
    )

    assert session == CheckoutSession(id="cs_test_1", url="https://checkout.stripe.com/c/pay/1")
    assert calls == [
        {
            "mode": "payment",
            "line_items": [
                {
                    "price_data": {"currency": "usd", "product_data": {"name": "The Matrix"}, "unit_amount": 999},
                    "quantity": 1,
                },
                {
                    "price_data": {"currency": "usd", "product_data": {"name": "Inception"}, "unit_amount": 749},
                    "quantity": 1,
                },
            ],
            "metadata": {"order_id": "5"},
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        }
    ]


async def test_stripe_error_becomes_payment_gateway_error(monkeypatch, gateway):
    replace_stripe_call(monkeypatch, gateway, error=stripe.APIConnectionError("network is down"))

    with pytest.raises(PaymentGatewayError, match="network is down"):
        await gateway.create_checkout_session(order_id=5, items=[CheckoutItem("The Matrix", Decimal("9.99"))])


async def test_session_without_a_payment_page_is_an_error(monkeypatch, gateway):
    replace_stripe_call(monkeypatch, gateway, result=stripe_session(None))

    with pytest.raises(PaymentGatewayError):
        await gateway.create_checkout_session(order_id=5, items=[CheckoutItem("The Matrix", Decimal("9.99"))])


def test_get_payment_gateway_uses_the_settings():
    get_payment_gateway.cache_clear()
    try:
        gateway = get_payment_gateway()
        assert (gateway._success_url, gateway._cancel_url) == (settings.STRIPE_SUCCESS_URL, settings.STRIPE_CANCEL_URL)
        assert get_payment_gateway() is gateway
    finally:
        get_payment_gateway.cache_clear()
