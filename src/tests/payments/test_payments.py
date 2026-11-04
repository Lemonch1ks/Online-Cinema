import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select, update

from src.auth.models import UserGroupEnum
from src.core.config import settings
from src.main import app
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import BaseEmailError
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.payments import services as payment_services
from src.payments.models import Payment, PaymentItem, PaymentStatusEnum
from src.tests.conftest import FakePaymentGateway
from src.tests.orders.test_orders import ORDERS_URL, place_order, set_status
from src.tests.utils import headers_for

API = settings.API_VERSION_PREFIX
WEBHOOK_URL = f"{API}/payments/webhook"
PAYMENTS_URL = f"{API}/payments"
ADMIN_PAYMENTS_URL = f"{API}/admins/payments"
PURCHASES_URL = f"{API}/purchases"
TRY_ANOTHER_METHOD = "The payment was not completed. Try a different payment method."


def stripe_event(
    event_type: str,
    session_id: str = "cs_test_fake_1",
    order_id: int | None = None,
    amount_total: int | None = None,
    payment_status: str = "paid",
    payment_intent: str | None = "pi_test_1",
) -> bytes:
    """A Stripe event body with a Checkout Session inside, as Stripe sends it."""
    session = {
        "id": session_id,
        "object": "checkout.session",
        "amount_total": amount_total,
        "payment_status": payment_status,
        "payment_intent": payment_intent,
        "metadata": {} if order_id is None else {"order_id": str(order_id)},
    }
    return json.dumps({"id": "evt_test_1", "object": "event", "type": event_type, "data": {"object": session}}).encode()


async def send_event(client, payload: bytes, signature: str | None = FakePaymentGateway.SIGNATURE):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["Stripe-Signature"] = signature
    return await client.post(WEBHOOK_URL, content=payload, headers=headers)


async def open_checkout(client, member, payment_gateway, *movies) -> tuple[dict, str]:
    """Places an order and opens its payment page; returns the order and the Stripe session id."""
    order = await place_order(client, member, *movies)
    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=member.headers)
    assert response.status_code == 200, response.text
    _, _, session = payment_gateway.sessions[-1]
    return order, session.id


def paid_event(order: dict, session_id: str, payment_intent: str = "pi_test_1", cents: int | None = None) -> bytes:
    total = cents if cents is not None else int(Decimal(order["total_amount"]) * 100)
    return stripe_event("checkout.session.completed", session_id, order["id"], total, payment_intent=payment_intent)


async def buy(client, member, payment_gateway, *movies, payment_intent: str = "pi_test_1") -> dict:
    """The whole purchase: order, payment page, Stripe confirms the payment."""
    order, session_id = await open_checkout(client, member, payment_gateway, *movies)
    response = await send_event(client, paid_event(order, session_id, payment_intent))
    assert response.status_code == 200, response.text
    return order


async def payments_in_db(db_session) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.id).execution_options(populate_existing=True)
    return list(await db_session.scalars(stmt))


async def order_status(db_session, order_id: int) -> OrderStatusEnum:
    return (await db_session.get(Order, order_id, populate_existing=True)).status


@pytest.fixture()
async def admin_headers(client, db_session) -> dict:
    return await headers_for(client, db_session, UserGroupEnum.ADMIN, "admin@example.com")


# --- access ---


async def test_anonymous_gets_401(client):
    responses = [
        await client.get(PAYMENTS_URL),
        await client.get(ADMIN_PAYMENTS_URL),
        await client.get(PURCHASES_URL),
        await client.get(f"{PAYMENTS_URL}/checkout/cs_test_fake_1"),
    ]

    assert [response.status_code for response in responses] == [401] * 4


# --- webhook: successful payment ---


async def test_paid_checkout_saves_the_payment_and_marks_the_order_paid(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    order, session_id = await open_checkout(client, alice, payment_gateway, matrix, inception)

    response = await send_event(client, paid_event(order, session_id, "pi_test_1"))

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.paid
    [payment] = await payments_in_db(db_session)
    assert (payment.user_id, payment.order_id, payment.status, payment.amount, payment.external_payment_id) == (
        alice.id,
        order["id"],
        PaymentStatusEnum.successful,
        Decimal("17.48"),
        "pi_test_1",
    )
    stmt = (
        select(OrderItem.movie_id, PaymentItem.price_at_payment)
        .join(OrderItem, OrderItem.id == PaymentItem.order_item_id)
        .where(PaymentItem.payment_id == payment.id)
    )
    assert sorted((await db_session.execute(stmt)).all()) == sorted(
        [(matrix.id, Decimal("9.99")), (inception.id, Decimal("7.49"))]
    )
    assert email_sender.payment_success_emails == [(alice.email, settings.PURCHASES_LINK_ENDPOINT)]
    assert payment_gateway.refunds == []


async def test_the_same_event_twice_saves_one_payment(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])

    first = await send_event(client, paid_event(order, session_id))
    second = await send_event(client, paid_event(order, session_id))

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(await payments_in_db(db_session)) == 1
    assert len(email_sender.payment_success_emails) == 1
    assert payment_gateway.refunds == []  # a repeated event is not "a second payment" to return
    assert email_sender.refund_emails == []


async def test_duplicate_event_at_the_same_moment_saves_one_payment(
    client, db_session, catalog, alice, payment_gateway, email_sender, monkeypatch
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await send_event(client, paid_event(order, session_id))

    # The second request did its check before the first one committed: only the unique index stops it.
    async def not_saved_yet(db, external_payment_id):
        return False

    monkeypatch.setattr(payment_services, "payment_exists", not_saved_yet)
    await set_status(db_session, order["id"], OrderStatusEnum.pending)
    response = await send_event(client, paid_event(order, session_id))

    assert response.status_code == 200
    assert len(await payments_in_db(db_session)) == 1
    assert len(email_sender.payment_success_emails) == 1


async def test_delayed_payment_is_saved_when_stripe_confirms_it(client, db_session, catalog, alice, payment_gateway):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    started = stripe_event("checkout.session.completed", session_id, order["id"], 999, payment_status="unpaid")

    await send_event(client, started)

    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending
    assert await payments_in_db(db_session) == []

    await send_event(client, stripe_event("checkout.session.async_payment_succeeded", session_id, order["id"], 999))

    assert await order_status(db_session, order["id"]) == OrderStatusEnum.paid
    assert len(await payments_in_db(db_session)) == 1


async def test_paid_movie_is_purchased(client, catalog, alice, payment_gateway):
    matrix = catalog["The Matrix"]
    await buy(client, alice, payment_gateway, matrix)

    response = await client.post(f"{API}/cart/items", json={"movie_id": matrix.id}, headers=alice.headers)

    assert response.status_code == 409


# --- webhook: payments that cannot be accepted ---


async def test_payment_with_another_amount_is_refunded(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])

    response = await send_event(client, paid_event(order, session_id, "pi_test_1", cents=100))

    assert response.status_code == 200
    assert payment_gateway.refunds == ["pi_test_1"]
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending
    [payment] = await payments_in_db(db_session)
    assert (payment.status, payment.amount) == (PaymentStatusEnum.refunded, Decimal("1.00"))
    assert email_sender.refund_emails == [(alice.email, settings.ORDERS_LINK_ENDPOINT)]
    assert email_sender.payment_success_emails == []


async def test_payment_for_a_canceled_order_is_refunded(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await set_status(db_session, order["id"], OrderStatusEnum.canceled)

    await send_event(client, paid_event(order, session_id))

    assert payment_gateway.refunds == ["pi_test_1"]
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.canceled
    [payment] = await payments_in_db(db_session)
    assert payment.status == PaymentStatusEnum.refunded


async def test_second_payment_for_a_paid_order_is_refunded(client, db_session, catalog, alice, payment_gateway):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await send_event(client, paid_event(order, session_id, "pi_test_1"))

    await send_event(client, paid_event(order, session_id, "pi_test_2"))

    assert payment_gateway.refunds == ["pi_test_2"]
    statuses = [payment.status for payment in await payments_in_db(db_session)]
    assert statuses == [PaymentStatusEnum.successful, PaymentStatusEnum.refunded]


async def test_failed_refund_gives_502_so_stripe_sends_the_event_again(
    client, db_session, catalog, alice, payment_gateway
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    payment_gateway.fail = True

    response = await send_event(client, paid_event(order, session_id, cents=100))

    assert response.status_code == 502
    assert await payments_in_db(db_session) == []


@pytest.mark.parametrize(
    "payload",
    [
        stripe_event("checkout.session.completed", order_id=999999, amount_total=999),
        stripe_event("checkout.session.completed", order_id=None, amount_total=999),
        stripe_event("checkout.session.completed", order_id=1, amount_total=999, payment_intent=None),
        stripe_event("payment_intent.created"),
    ],
    ids=["unknown order", "no order id", "no payment intent", "other event type"],
)
async def test_events_without_a_payment_to_save_are_accepted_and_ignored(
    client, db_session, payload, payment_gateway, email_sender
):
    response = await send_event(client, payload)

    assert response.status_code == 200
    assert await payments_in_db(db_session) == []
    assert payment_gateway.refunds == []
    assert email_sender.payment_success_emails == email_sender.payment_failed_emails == []


# --- webhook: signature ---


@pytest.mark.parametrize("signature", ["t=1,v1=forged", None], ids=["wrong signature", "no signature"])
async def test_event_without_a_valid_signature_gives_400_and_changes_nothing(
    client, db_session, catalog, alice, payment_gateway, signature
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])

    response = await send_event(client, paid_event(order, session_id), signature=signature)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Stripe signature or payload."
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending
    assert await payments_in_db(db_session) == []


async def test_body_that_is_not_an_event_gives_400(client):
    response = await send_event(client, b"not json")

    assert response.status_code == 400


# --- webhook: declined or expired payment ---


@pytest.mark.parametrize("event_type", ["checkout.session.expired", "checkout.session.async_payment_failed"])
async def test_failed_payment_suggests_another_payment_method(
    client, db_session, catalog, alice, payment_gateway, email_sender, event_type
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])

    response = await send_event(client, stripe_event(event_type, session_id, order["id"], payment_status="unpaid"))

    assert response.status_code == 200
    assert email_sender.payment_failed_emails == [(alice.email, settings.ORDERS_LINK_ENDPOINT)]
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending


async def test_page_closed_by_a_new_pay_is_not_reported(client, catalog, alice, payment_gateway, email_sender):
    order, old_session = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    await send_event(client, stripe_event("checkout.session.expired", old_session, order["id"]))

    assert email_sender.payment_failed_emails == []


async def test_page_of_a_canceled_order_is_not_reported(client, catalog, alice, payment_gateway, email_sender):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    await send_event(client, stripe_event("checkout.session.expired", session_id, order["id"]))

    assert email_sender.payment_failed_emails == []


async def test_failed_event_without_a_session_is_ignored(client, catalog, alice, payment_gateway, email_sender):
    await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    payload = json.dumps(
        {"type": "checkout.session.expired", "data": {"object": {"object": "checkout.session"}}}
    ).encode()

    response = await send_event(client, payload)

    assert response.status_code == 200
    assert email_sender.payment_failed_emails == []


# --- checkout result for the redirect page ---


@pytest.mark.parametrize(
    ("page_status", "result", "message"),
    [
        ("open", "not_completed", TRY_ANOTHER_METHOD),
        ("expired", "not_completed", TRY_ANOTHER_METHOD),
        ("complete", "processing", "The payment is being confirmed. You will get an email when it is done."),
    ],
)
async def test_checkout_result_of_a_pending_order(
    client, catalog, alice, payment_gateway, page_status, result, message
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    payment_gateway.statuses[session_id] = page_status

    response = await client.get(f"{PAYMENTS_URL}/checkout/{session_id}", headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == {
        "order_id": order["id"],
        "order_status": "pending",
        "result": result,
        "message": message,
    }


async def test_checkout_result_of_a_paid_order(client, catalog, alice, payment_gateway):
    order = await buy(client, alice, payment_gateway, catalog["The Matrix"])
    [(_, _, session)] = payment_gateway.sessions
    payment_gateway.fail = True  # a paid order is answered from the database

    response = await client.get(f"{PAYMENTS_URL}/checkout/{session.id}", headers=alice.headers)

    assert response.json() == {
        "order_id": order["id"],
        "order_status": "paid",
        "result": "paid",
        "message": "Payment successful. The movies are in your purchases.",
    }


async def test_checkout_result_of_a_canceled_order(client, catalog, alice, payment_gateway):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    response = await client.get(f"{PAYMENTS_URL}/checkout/{session_id}", headers=alice.headers)

    assert response.json()["result"] == "canceled"
    assert response.json()["message"] == "The order is canceled."


async def test_checkout_result_of_another_users_page_gives_404(client, catalog, alice, bob, payment_gateway):
    _, session_id = await open_checkout(client, bob, payment_gateway, catalog["The Matrix"])

    other = await client.get(f"{PAYMENTS_URL}/checkout/{session_id}", headers=alice.headers)
    unknown = await client.get(f"{PAYMENTS_URL}/checkout/cs_test_unknown", headers=alice.headers)

    assert (other.status_code, unknown.status_code) == (404, 404)
    assert other.json()["detail"] == "No order with this payment page found."


async def test_checkout_result_when_stripe_fails_gives_502(client, catalog, alice, payment_gateway):
    _, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    payment_gateway.fail = True

    response = await client.get(f"{PAYMENTS_URL}/checkout/{session_id}", headers=alice.headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "Payment provider is unavailable, try again later."


# --- payment history ---


async def test_user_sees_own_payments_newest_first(client, db_session, catalog, alice, bob, payment_gateway):
    first = await buy(client, alice, payment_gateway, catalog["The Matrix"], payment_intent="pi_test_1")
    await buy(client, bob, payment_gateway, catalog["Inception"], payment_intent="pi_test_2")
    second = await buy(client, alice, payment_gateway, catalog["Forrest Gump"], payment_intent="pi_test_3")

    response = await client.get(PAYMENTS_URL, headers=alice.headers)

    assert response.status_code == 200
    body = response.json()
    assert [payment["order_id"] for payment in body] == [second["id"], first["id"]]
    assert body[1] == {
        "id": body[1]["id"],
        "user_id": alice.id,
        "order_id": first["id"],
        "created_at": body[1]["created_at"],
        "status": "successful",
        "amount": "9.99",
        "items": [{"movie_id": catalog["The Matrix"].id, "name": "The Matrix", "price_at_payment": "9.99"}],
    }


async def test_refunded_payment_is_shown_as_refunded(client, catalog, alice, payment_gateway):
    order = await buy(client, alice, payment_gateway, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    response = await client.get(PAYMENTS_URL, headers=alice.headers)

    assert [payment["status"] for payment in response.json()] == ["refunded"]


async def make_payments(client, db_session, catalog, alice, bob, payment_gateway) -> dict[str, int]:
    """Three payments: alice's refunded on Jan 10, bob's on Jan 20, alice's on Feb 1 (2026, UTC)."""
    refunded = await buy(client, alice, payment_gateway, catalog["The Matrix"], payment_intent="pi_test_1")
    await client.post(f"{ORDERS_URL}/{refunded['id']}/refund", headers=alice.headers)
    bobs = await buy(client, bob, payment_gateway, catalog["Inception"], payment_intent="pi_test_2")
    latest = await buy(client, alice, payment_gateway, catalog["Forrest Gump"], payment_intent="pi_test_3")
    ids = {}
    for name, order, day in [("refunded", refunded, (1, 10)), ("bobs", bobs, (1, 20)), ("latest", latest, (2, 1))]:
        created = datetime(2026, *day, 12, tzinfo=UTC)
        await db_session.execute(update(Payment).where(Payment.order_id == order["id"]).values(created_at=created))
        ids[name] = await db_session.scalar(select(Payment.id).where(Payment.order_id == order["id"]))
    await db_session.commit()
    return ids


def payment_ids(response) -> list[int]:
    return [payment["id"] for payment in response.json()["payments"]]


async def test_admin_sees_all_payments_newest_first(
    client, db_session, catalog, alice, bob, payment_gateway, admin_headers
):
    ids = await make_payments(client, db_session, catalog, alice, bob, payment_gateway)

    response = await client.get(ADMIN_PAYMENTS_URL, headers=admin_headers)

    assert response.status_code == 200
    assert payment_ids(response) == [ids["latest"], ids["bobs"], ids["refunded"]]
    assert (response.json()["total_items"], response.json()["total_pages"]) == (3, 1)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "refunded"}, ["refunded"]),
        ({"status": "successful"}, ["latest", "bobs"]),
        ({"date_from": "2026-01-20"}, ["latest", "bobs"]),
        ({"date_to": "2026-01-20"}, ["bobs", "refunded"]),
        ({"date_from": "2026-01-11", "date_to": "2026-01-31"}, ["bobs"]),
    ],
)
async def test_admin_filters_payments(
    client, db_session, catalog, alice, bob, payment_gateway, admin_headers, params, expected
):
    ids = await make_payments(client, db_session, catalog, alice, bob, payment_gateway)

    response = await client.get(ADMIN_PAYMENTS_URL, params=params, headers=admin_headers)

    assert payment_ids(response) == [ids[name] for name in expected]


async def test_admin_filters_payments_by_user(client, db_session, catalog, alice, bob, payment_gateway, admin_headers):
    ids = await make_payments(client, db_session, catalog, alice, bob, payment_gateway)

    response = await client.get(ADMIN_PAYMENTS_URL, params={"user_id": bob.id}, headers=admin_headers)

    assert payment_ids(response) == [ids["bobs"]]


async def test_admin_payments_are_paginated_with_links_keeping_filters(
    client, db_session, catalog, alice, bob, payment_gateway, admin_headers
):
    ids = await make_payments(client, db_session, catalog, alice, bob, payment_gateway)

    response = await client.get(
        ADMIN_PAYMENTS_URL, params={"user_id": alice.id, "per_page": 1, "page": 1}, headers=admin_headers
    )

    body = response.json()
    assert payment_ids(response) == [ids["latest"]]
    assert (body["total_items"], body["total_pages"], body["prev_page"]) == (2, 2, None)
    next_url = urlsplit(body["next_page"])
    assert next_url.path == ADMIN_PAYMENTS_URL
    assert parse_qs(next_url.query) == {"user_id": [str(alice.id)], "per_page": ["1"], "page": ["2"]}
    second = await client.get(body["next_page"], headers=admin_headers)
    assert payment_ids(second) == [ids["refunded"]]
    assert second.json()["next_page"] is None


async def test_admin_invalid_payment_filters_give_422(client, admin_headers):
    responses = [
        await client.get(ADMIN_PAYMENTS_URL, params={"status": "lost"}, headers=admin_headers),
        await client.get(
            ADMIN_PAYMENTS_URL, params={"date_from": "2026-02-01", "date_to": "2026-01-01"}, headers=admin_headers
        ),
    ]

    assert [response.status_code for response in responses] == [422, 422]


@pytest.mark.parametrize("group", [UserGroupEnum.USER, UserGroupEnum.MODERATOR])
async def test_not_admin_cannot_see_all_payments(client, db_session, group):
    headers = await headers_for(client, db_session, group, "curious@example.com")

    response = await client.get(ADMIN_PAYMENTS_URL, headers=headers)

    assert response.status_code == 403


# --- purchased movies ---


async def test_purchases_list_the_paid_movies_with_the_price_paid(
    client, db_session, catalog, alice, bob, payment_gateway
):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await buy(client, alice, payment_gateway, matrix, inception, payment_intent="pi_test_1")
    await buy(client, bob, payment_gateway, catalog["Forrest Gump"], payment_intent="pi_test_2")
    await place_order(client, alice, catalog["Cast Away"])  # ordered, not paid
    paid_at = await db_session.scalar(select(Payment.created_at).where(Payment.user_id == alice.id))

    response = await client.get(PURCHASES_URL, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "movie_id": inception.id,
            "name": "Inception",
            "year": inception.year,
            "price_paid": "7.49",
            "purchased_at": paid_at.isoformat().replace("+00:00", "Z"),
        },
        {
            "movie_id": matrix.id,
            "name": "The Matrix",
            "year": matrix.year,
            "price_paid": "9.99",
            "purchased_at": paid_at.isoformat().replace("+00:00", "Z"),
        },
    ]


async def test_refunded_movies_are_not_purchases(client, db_session, catalog, alice, payment_gateway):
    order = await buy(client, alice, payment_gateway, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    response = await client.get(PURCHASES_URL, headers=alice.headers)

    assert response.json() == []
    assert (await db_session.execute(select(func.count()).select_from(Payment))).scalar_one() == 1


async def test_email_failure_does_not_lose_the_payment(client, db_session, catalog, alice, payment_gateway):
    class BrokenSender:
        async def send_payment_success_email(self, email: str, purchases_link: str) -> None:
            raise BaseEmailError("broker is down")

    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    app.dependency_overrides[get_email_sender] = BrokenSender

    response = await send_event(client, paid_event(order, session_id))

    assert response.status_code == 200
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.paid
    assert len(await payments_in_db(db_session)) == 1


async def test_two_copies_of_an_event_at_once_save_one_payment_and_refund_nothing(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    order, session_id = await open_checkout(client, alice, payment_gateway, catalog["The Matrix"])
    payload = paid_event(order, session_id)

    responses = await asyncio.gather(send_event(client, payload), send_event(client, payload))

    assert [response.status_code for response in responses] == [200, 200]
    assert len(await payments_in_db(db_session)) == 1
    assert payment_gateway.refunds == []
    assert len(email_sender.payment_success_emails) == 1
