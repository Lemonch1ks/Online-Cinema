"""StripeGateway without the network: the Stripe API call is replaced, the rest of the gateway is real."""

import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
import stripe

from src.core.config import settings
from src.payments.dependencies import get_payment_gateway
from src.payments.gateway import (
    CheckoutItem,
    CheckoutSession,
    InvalidWebhookError,
    PaymentGatewayError,
    StripeGateway,
    WebhookEvent,
    from_cents,
    to_cents,
)

SUCCESS_URL = "http://test/success?session_id={CHECKOUT_SESSION_ID}"
CANCEL_URL = "http://test/cancel"
WEBHOOK_SECRET = "whsec_test_secret"


@pytest.fixture()
def gateway() -> StripeGateway:
    return StripeGateway("sk_test_x", WEBHOOK_SECRET, SUCCESS_URL, CANCEL_URL)


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
        assert (gateway._success_url, gateway._cancel_url, gateway._webhook_secret) == (
            settings.STRIPE_SUCCESS_URL,
            settings.STRIPE_CANCEL_URL,
            settings.STRIPE_WEBHOOK_SECRET,
        )
        assert get_payment_gateway() is gateway
    finally:
        get_payment_gateway.cache_clear()


def test_from_cents():
    assert from_cents(1748) == Decimal("17.48")


# --- payment page status, closing, refund ---


def replace_service(monkeypatch, service, name: str, results: list, error: Exception | None = None) -> list:
    """Replaces one async method of a Stripe service; returns the calls (positional args and params)."""
    calls = []

    async def call(*args, params=None):
        calls.append((args, params))
        if error is not None:
            raise error
        return results.pop(0)

    monkeypatch.setattr(service, name, call)
    return calls


def session_with_status(status: str) -> stripe.checkout.Session:
    return stripe.checkout.Session.construct_from({"id": "cs_test_1", "status": status}, "sk_test_x")


async def test_get_checkout_status(monkeypatch, gateway):
    sessions = gateway._client.v1.checkout.sessions
    calls = replace_service(monkeypatch, sessions, "retrieve_async", [session_with_status("complete")])

    assert await gateway.get_checkout_status("cs_test_1") == "complete"
    assert calls == [(("cs_test_1",), None)]


async def test_close_expires_an_open_page(monkeypatch, gateway):
    sessions = gateway._client.v1.checkout.sessions
    replace_service(monkeypatch, sessions, "retrieve_async", [session_with_status("open")])
    expired = replace_service(monkeypatch, sessions, "expire_async", [session_with_status("expired")])

    assert await gateway.close_checkout_session("cs_test_1") == "expired"
    assert expired == [(("cs_test_1",), None)]


@pytest.mark.parametrize("status", ["complete", "expired"])
async def test_close_leaves_a_paid_or_expired_page_as_is(monkeypatch, gateway, status):
    sessions = gateway._client.v1.checkout.sessions
    replace_service(monkeypatch, sessions, "retrieve_async", [session_with_status(status)])
    expired = replace_service(monkeypatch, sessions, "expire_async", [])

    assert await gateway.close_checkout_session("cs_test_1") == status
    assert expired == []


async def test_refund_the_whole_payment(monkeypatch, gateway):
    calls = replace_service(monkeypatch, gateway._client.v1.refunds, "create_async", [None])

    await gateway.refund("pi_test_1")

    assert calls == [((), {"payment_intent": "pi_test_1"})]


@pytest.mark.parametrize(
    ("service", "name", "call"),
    [
        ("sessions", "retrieve_async", lambda gateway: gateway.get_checkout_status("cs_test_1")),
        ("sessions", "retrieve_async", lambda gateway: gateway.close_checkout_session("cs_test_1")),
        ("refunds", "create_async", lambda gateway: gateway.refund("pi_test_1")),
    ],
    ids=["status", "close", "refund"],
)
async def test_stripe_errors_become_payment_gateway_errors(monkeypatch, gateway, service, name, call):
    target = gateway._client.v1.checkout.sessions if service == "sessions" else gateway._client.v1.refunds
    replace_service(monkeypatch, target, name, [], error=stripe.APIConnectionError("network is down"))

    with pytest.raises(PaymentGatewayError, match="network is down"):
        await call(gateway)


# --- webhook signature, checked by the real Stripe SDK ---


def signed(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def event_body(event_type: str, data_object: dict) -> bytes:
    return json.dumps({"id": "evt_1", "object": "event", "type": event_type, "data": {"object": data_object}}).encode()


def test_parse_a_signed_checkout_event(gateway):
    payload = event_body(
        "checkout.session.completed",
        {
            "id": "cs_test_1",
            "object": "checkout.session",
            "payment_status": "paid",
            "amount_total": 1748,
            "payment_intent": "pi_test_1",
            "metadata": {"order_id": "5"},
        },
    )

    assert gateway.parse_event(payload, signed(payload)) == WebhookEvent(
        type="checkout.session.completed",
        session_id="cs_test_1",
        order_id=5,
        payment_status="paid",
        amount_total=1748,
        payment_intent="pi_test_1",
    )


def test_other_events_keep_only_their_type(gateway):
    payload = event_body("payment_intent.created", {"id": "pi_test_1", "object": "payment_intent"})

    assert gateway.parse_event(payload, signed(payload)) == WebhookEvent(type="payment_intent.created")


@pytest.mark.parametrize("order_id", [None, "abc"], ids=["no metadata", "not a number"])
def test_checkout_event_without_a_valid_order_id(gateway, order_id):
    metadata = None if order_id is None else {"order_id": order_id}
    payload = event_body(
        "checkout.session.expired", {"id": "cs_test_1", "object": "checkout.session", "metadata": metadata}
    )

    assert gateway.parse_event(payload, signed(payload)).order_id is None


@pytest.mark.parametrize(
    "signature",
    [None, "t=1,v1=forged", "other-secret"],
    ids=["no header", "forged", "signed with another secret"],
)
def test_event_without_a_valid_signature_is_rejected(gateway, signature):
    payload = event_body("checkout.session.completed", {"id": "cs_test_1", "object": "checkout.session"})
    header = signed(payload, "whsec_other") if signature == "other-secret" else signature

    with pytest.raises(InvalidWebhookError):
        gateway.parse_event(payload, header)


def test_signed_body_that_is_not_json_is_rejected(gateway):
    with pytest.raises(InvalidWebhookError):
        gateway.parse_event(b"not json", signed(b"not json"))
