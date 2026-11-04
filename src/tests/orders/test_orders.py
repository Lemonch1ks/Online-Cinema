from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select, update

from src.auth.models import User, UserGroupEnum
from src.cart.models import Cart, CartItem
from src.core.config import settings
from src.movies.models import Movie
from src.orders.models import Order, OrderItem, OrderStatusEnum
from src.payments.gateway import CheckoutItem
from src.payments.models import Payment, PaymentStatusEnum
from src.tests.utils import MOVIES_URL, headers_for

ORDERS_URL = f"{settings.API_VERSION_PREFIX}/orders"
ADMIN_ORDERS_URL = f"{settings.API_VERSION_PREFIX}/admins/orders"
CART_ITEMS_URL = f"{settings.API_VERSION_PREFIX}/cart/items"


async def put_in_cart(client, member, *movies) -> None:
    for movie in movies:
        response = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=member.headers)
        assert response.status_code == 201, response.text


async def place_order(client, member, *movies) -> dict:
    await put_in_cart(client, member, *movies)
    response = await client.post(ORDERS_URL, headers=member.headers)
    assert response.status_code == 201, response.text
    return response.json()


async def set_status(db_session, order_id: int, status: OrderStatusEnum) -> None:
    await db_session.execute(update(Order).where(Order.id == order_id).values(status=status))
    await db_session.commit()


async def cart_movie_ids(db_session, user_id: int) -> list[int]:
    stmt = select(CartItem.movie_id).join(Cart, Cart.id == CartItem.cart_id).where(Cart.user_id == user_id)
    return sorted(await db_session.scalars(stmt))


async def order_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(Order))).scalar_one()


def movie_names(order: dict) -> list[str]:
    return [item["name"] for item in order["items"]]


async def order_status(db_session, order_id: int) -> OrderStatusEnum:
    return (await db_session.get(Order, order_id, populate_existing=True)).status


@pytest.fixture()
async def admin_headers(client, db_session) -> dict:
    return await headers_for(client, db_session, UserGroupEnum.ADMIN, "admin@example.com")


# --- access ---


async def test_anonymous_gets_401(client):
    responses = [
        await client.post(ORDERS_URL),
        await client.get(ORDERS_URL),
        await client.post(f"{ORDERS_URL}/1/cancel"),
        await client.get(ADMIN_ORDERS_URL),
        await client.post(f"{ORDERS_URL}/1/pay"),
        await client.post(f"{ORDERS_URL}/1/refund"),
    ]

    assert [response.status_code for response in responses] == [401] * 6


# --- place an order ---


async def test_place_order_saves_items_with_prices_and_clears_the_cart(client, db_session, catalog, alice):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]

    body = await place_order(client, alice, matrix, inception)

    assert body == {
        "id": body["id"],
        "user_id": alice.id,
        "created_at": body["created_at"],
        "status": "pending",
        "total_amount": "17.48",
        "items": [
            {"movie_id": matrix.id, "name": "The Matrix", "price_at_order": "9.99"},
            {"movie_id": inception.id, "name": "Inception", "price_at_order": "7.49"},
        ],
        "excluded": [],
    }
    order = await db_session.get(Order, body["id"])
    assert (order.user_id, order.status, order.total_amount) == (alice.id, OrderStatusEnum.pending, Decimal("17.48"))
    rows = (await db_session.execute(select(OrderItem.movie_id, OrderItem.price_at_order))).all()
    assert sorted(rows) == sorted([(matrix.id, Decimal("9.99")), (inception.id, Decimal("7.49"))])
    assert await cart_movie_ids(db_session, alice.id) == []


async def test_place_order_with_an_empty_cart_gives_400(client, db_session, alice):
    response = await client.post(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "The cart is empty."
    assert await order_count(db_session) == 0


async def test_place_order_after_clearing_the_cart_gives_400(client, db_session, catalog, alice):
    await put_in_cart(client, alice, catalog["The Matrix"])
    await client.delete(f"{settings.API_VERSION_PREFIX}/cart", headers=alice.headers)

    response = await client.post(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 400
    assert await order_count(db_session) == 0


async def test_order_does_not_take_other_users_cart(client, db_session, catalog, alice, bob):
    await put_in_cart(client, bob, catalog["Forrest Gump"])

    body = await place_order(client, alice, catalog["The Matrix"])

    assert movie_names(body) == ["The Matrix"]
    assert await cart_movie_ids(db_session, bob.id) == [catalog["Forrest Gump"].id]


async def test_movie_in_a_pending_order_is_excluded_from_a_new_one(client, db_session, catalog, alice):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    first = await place_order(client, alice, matrix)
    await put_in_cart(client, alice, matrix, inception)

    response = await client.post(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 201
    body = response.json()
    assert movie_names(body) == ["Inception"]
    assert body["total_amount"] == "7.49"
    assert body["excluded"] == [{"movie_id": matrix.id, "name": "The Matrix", "reason": "pending_order"}]
    assert body["id"] != first["id"]
    assert await cart_movie_ids(db_session, alice.id) == []


async def test_purchased_and_pending_movies_are_excluded_with_reasons(client, db_session, catalog, alice):
    matrix, inception, cast_away = catalog["The Matrix"], catalog["Inception"], catalog["Cast Away"]
    bought = await place_order(client, alice, matrix)
    await place_order(client, alice, inception)
    await put_in_cart(client, alice, matrix, inception, cast_away)  # matrix is not paid yet, so the cart allows it
    await set_status(db_session, bought["id"], OrderStatusEnum.paid)

    response = await client.post(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 201
    body = response.json()
    assert movie_names(body) == ["Cast Away"]
    assert body["total_amount"] == "14.99"
    assert body["excluded"] == [
        {"movie_id": matrix.id, "name": "The Matrix", "reason": "purchased"},
        {"movie_id": inception.id, "name": "Inception", "reason": "pending_order"},
    ]


async def test_movie_of_a_canceled_order_can_be_ordered_again(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    first = await place_order(client, alice, matrix)
    await set_status(db_session, first["id"], OrderStatusEnum.canceled)

    body = await place_order(client, alice, matrix)

    assert movie_names(body) == ["The Matrix"]
    assert body["excluded"] == []


async def test_movie_in_another_users_order_is_not_excluded(client, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    bobs = await place_order(client, bob, matrix)
    assert movie_names(bobs) == ["The Matrix"]

    body = await place_order(client, alice, matrix)

    assert movie_names(body) == ["The Matrix"]
    assert body["excluded"] == []


async def test_when_every_movie_is_excluded_no_order_is_created_and_cart_is_kept(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await place_order(client, alice, matrix)
    await put_in_cart(client, alice, matrix)

    response = await client.post(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "None of the movies in the cart can be ordered."
    assert await order_count(db_session) == 1
    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]


async def test_order_keeps_the_price_when_the_movie_price_changes(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await place_order(client, alice, matrix)

    await db_session.execute(update(Movie).where(Movie.id == matrix.id).values(price=Decimal("19.99")))
    await db_session.commit()

    orders = (await client.get(ORDERS_URL, headers=alice.headers)).json()
    assert orders[0]["items"][0]["price_at_order"] == "9.99"
    assert orders[0]["total_amount"] == "9.99"


# --- list my orders ---


async def test_user_sees_own_orders_newest_first(client, catalog, alice, bob):
    first = await place_order(client, alice, catalog["The Matrix"])
    await place_order(client, bob, catalog["Forrest Gump"])
    second = await place_order(client, alice, catalog["Inception"])

    response = await client.get(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 200
    body = response.json()
    assert [order["id"] for order in body] == [second["id"], first["id"]]
    assert {key: body[0][key] for key in ("status", "total_amount")} == {"status": "pending", "total_amount": "7.49"}
    assert movie_names(body[0]) == ["Inception"]
    assert "excluded" not in body[0]


async def test_user_without_orders_gets_an_empty_list(client, alice):
    response = await client.get(ORDERS_URL, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == []


# --- cancel ---


async def test_cancel_pending_order(client, db_session, catalog, alice):
    order = await place_order(client, alice, catalog["The Matrix"])

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    assert (await db_session.get(Order, order["id"], populate_existing=True)).status == OrderStatusEnum.canceled


@pytest.mark.parametrize("status", [OrderStatusEnum.paid, OrderStatusEnum.canceled])
async def test_cancel_order_that_is_not_pending_gives_409(client, db_session, catalog, alice, status):
    order = await place_order(client, alice, catalog["The Matrix"])
    await set_status(db_session, order["id"], status)

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "Only pending orders can be canceled."
    assert (await db_session.get(Order, order["id"], populate_existing=True)).status == status


async def test_cancel_closes_the_open_payment_page(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)
    [(_, _, session)] = payment_gateway.sessions

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 200
    assert payment_gateway.statuses[session.id] == "expired"


async def test_cancel_after_the_page_was_paid_gives_409(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)
    [(_, _, session)] = payment_gateway.sessions
    payment_gateway.statuses[session.id] = "complete"

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The order has just been paid, the payment is being confirmed. Request a refund instead."
    )
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending


async def test_cancel_when_stripe_fails_gives_502(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)
    payment_gateway.fail = True

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 502
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending


async def test_cancel_other_users_order_gives_404(client, db_session, catalog, alice, bob):
    order = await place_order(client, bob, catalog["The Matrix"])

    response = await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=alice.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == f"No orders with id:{order['id']} found."
    assert (await db_session.get(Order, order["id"], populate_existing=True)).status == OrderStatusEnum.pending


async def test_cancel_unknown_order_gives_404(client, alice):
    response = await client.post(f"{ORDERS_URL}/999999/cancel", headers=alice.headers)

    assert response.status_code == 404


# --- pay ---


async def test_pay_opens_a_checkout_page_with_every_movie_of_the_order(
    client, db_session, catalog, alice, payment_gateway
):
    order = await place_order(client, alice, catalog["The Matrix"], catalog["Inception"])

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 200
    [(order_id, items, session)] = payment_gateway.sessions
    assert response.json() == {"checkout_url": session.url}
    assert order_id == order["id"]
    assert items == [CheckoutItem("The Matrix", Decimal("9.99")), CheckoutItem("Inception", Decimal("7.49"))]
    # The order is paid only when Stripe confirms the payment through the webhook.
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending


async def test_pay_after_a_price_change_updates_the_order_and_asks_to_confirm(
    client, db_session, catalog, alice, payment_gateway
):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    order = await place_order(client, alice, matrix, inception)
    await db_session.execute(update(Movie).where(Movie.id == matrix.id).values(price=Decimal("19.99")))
    await db_session.commit()

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Prices have changed since the order was placed. New total: 27.48. Pay again to confirm."
    )
    assert payment_gateway.sessions == []
    saved = await db_session.get(Order, order["id"], populate_existing=True)
    assert saved.total_amount == Decimal("27.48")
    prices = dict((await db_session.execute(select(OrderItem.movie_id, OrderItem.price_at_order))).all())
    assert prices == {matrix.id: Decimal("19.99"), inception.id: Decimal("7.49")}

    confirmed = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert confirmed.status_code == 200
    [(_, items, _)] = payment_gateway.sessions
    assert items == [CheckoutItem("The Matrix", Decimal("19.99")), CheckoutItem("Inception", Decimal("7.49"))]


async def test_pay_saves_the_payment_page_of_the_order(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])

    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    [(_, _, session)] = payment_gateway.sessions
    saved = await db_session.get(Order, order["id"], populate_existing=True)
    assert saved.checkout_session_id == session.id


async def test_pay_again_closes_the_previous_payment_page(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])

    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)
    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 200
    first, second = (session.id for _, _, session in payment_gateway.sessions)
    assert payment_gateway.statuses == {first: "expired", second: "open"}
    saved = await db_session.get(Order, order["id"], populate_existing=True)
    assert saved.checkout_session_id == second


async def test_pay_when_the_previous_page_was_just_paid_gives_409(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)
    [(_, _, session)] = payment_gateway.sessions
    payment_gateway.statuses[session.id] = "complete"  # paid, the webhook has not arrived yet

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "The order has just been paid, the payment is being confirmed."
    assert len(payment_gateway.sessions) == 1


@pytest.mark.parametrize("status", [OrderStatusEnum.paid, OrderStatusEnum.canceled])
async def test_pay_for_order_that_is_not_pending_gives_409(client, db_session, catalog, alice, payment_gateway, status):
    order = await place_order(client, alice, catalog["The Matrix"])
    await set_status(db_session, order["id"], status)

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "Only pending orders can be paid."
    assert payment_gateway.sessions == []


async def test_pay_for_other_users_order_gives_404(client, db_session, catalog, alice, bob, payment_gateway):
    order = await place_order(client, bob, catalog["The Matrix"])

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == f"No orders with id:{order['id']} found."
    assert payment_gateway.sessions == []


async def test_pay_for_unknown_order_gives_404(client, alice, payment_gateway):
    response = await client.post(f"{ORDERS_URL}/999999/pay", headers=alice.headers)

    assert response.status_code == 404
    assert payment_gateway.sessions == []


async def test_pay_when_stripe_fails_gives_502_and_order_stays_pending(
    client, db_session, catalog, alice, payment_gateway
):
    order = await place_order(client, alice, catalog["The Matrix"])
    payment_gateway.fail = True

    response = await client.post(f"{ORDERS_URL}/{order['id']}/pay", headers=alice.headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "Payment provider is unavailable, try again later."
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.pending


# --- refund ---


async def mark_paid(db_session, order_id: int, payment_intent: str = "pi_test_1") -> None:
    """What the webhook does after a successful payment."""
    order = await db_session.get(Order, order_id)
    await db_session.refresh(order, ["items"])
    order.status = OrderStatusEnum.paid
    db_session.add(
        Payment(
            user_id=order.user_id,
            order_id=order.id,
            amount=order.total_amount,
            external_payment_id=payment_intent,
            items=[],
        )
    )
    await db_session.commit()


async def test_refund_returns_the_money_and_cancels_the_order(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    matrix = catalog["The Matrix"]
    order = await place_order(client, alice, matrix)
    await mark_paid(db_session, order["id"], "pi_test_1")

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    assert payment_gateway.refunds == ["pi_test_1"]
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.canceled
    payment = await db_session.scalar(select(Payment).execution_options(populate_existing=True))
    assert payment.status == PaymentStatusEnum.refunded
    assert email_sender.refund_emails == [(alice.email, settings.ORDERS_LINK_ENDPOINT)]
    # A refunded movie is not purchased any more.
    added = await client.post(CART_ITEMS_URL, json={"movie_id": matrix.id}, headers=alice.headers)
    assert added.status_code == 201


@pytest.mark.parametrize("status", [OrderStatusEnum.pending, OrderStatusEnum.canceled])
async def test_refund_order_that_is_not_paid_gives_409(
    client, db_session, catalog, alice, payment_gateway, email_sender, status
):
    order = await place_order(client, alice, catalog["The Matrix"])
    await set_status(db_session, order["id"], status)

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "Only paid orders can be refunded."
    assert payment_gateway.refunds == []
    assert email_sender.refund_emails == []


async def test_refund_twice_gives_409(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await mark_paid(db_session, order["id"])
    await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 409
    assert payment_gateway.refunds == ["pi_test_1"]


async def test_refund_other_users_order_gives_404(client, db_session, catalog, alice, bob, payment_gateway):
    order = await place_order(client, bob, catalog["The Matrix"])
    await mark_paid(db_session, order["id"])

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 404
    assert payment_gateway.refunds == []
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.paid


async def test_refund_when_stripe_fails_gives_502_and_keeps_the_order_paid(
    client, db_session, catalog, alice, payment_gateway, email_sender
):
    order = await place_order(client, alice, catalog["The Matrix"])
    await mark_paid(db_session, order["id"])
    payment_gateway.fail = True

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 502
    assert await order_status(db_session, order["id"]) == OrderStatusEnum.paid
    payment = await db_session.scalar(select(Payment).execution_options(populate_existing=True))
    assert payment.status == PaymentStatusEnum.successful
    assert email_sender.refund_emails == []


# --- purchased movies elsewhere ---


async def test_purchased_movie_cannot_be_added_to_the_cart(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    order = await place_order(client, alice, matrix)
    await set_status(db_session, order["id"], OrderStatusEnum.paid)

    response = await client.post(CART_ITEMS_URL, json={"movie_id": matrix.id}, headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == f"Movie with id:{matrix.id} is already purchased."
    assert await cart_movie_ids(db_session, alice.id) == []


async def test_movie_bought_by_another_user_can_be_added_to_the_cart(client, db_session, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    order = await place_order(client, bob, matrix)
    await set_status(db_session, order["id"], OrderStatusEnum.paid)

    await put_in_cart(client, alice, matrix)

    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]


@pytest.mark.parametrize("status", list(OrderStatusEnum))
@pytest.mark.parametrize("force", [False, True])
async def test_movie_in_any_order_cannot_be_deleted(
    client, db_session, catalog, alice, moderator_headers, status, force
):
    matrix = catalog["The Matrix"]
    order = await place_order(client, alice, matrix)
    await set_status(db_session, order["id"], status)

    response = await client.delete(f"{MOVIES_URL}/{matrix.id}", params={"force": force}, headers=moderator_headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "The movie is in 1 orders and cannot be deleted."
    assert await db_session.scalar(select(Movie.id).where(Movie.id == matrix.id)) == matrix.id


async def test_movie_without_orders_can_be_deleted_while_others_have_orders(
    client, db_session, catalog, alice, moderator_headers
):
    await place_order(client, alice, catalog["The Matrix"])
    inception = catalog["Inception"]

    response = await client.delete(f"{MOVIES_URL}/{inception.id}", headers=moderator_headers)

    assert response.status_code == 204
    assert await db_session.scalar(select(Movie.id).where(Movie.id == inception.id)) is None


# --- admin ---


async def make_orders(client, db_session, catalog, alice, bob) -> dict[str, dict]:
    """Three orders with fixed dates: alice pending (Jan 10), alice paid (Feb 20), bob canceled (Feb 25)."""
    orders = {
        "alice_pending": await place_order(client, alice, catalog["The Matrix"]),
        "alice_paid": await place_order(client, alice, catalog["Inception"]),
        "bob_canceled": await place_order(client, bob, catalog["Forrest Gump"]),
    }
    dates = {"alice_pending": (1, 10), "alice_paid": (2, 20), "bob_canceled": (2, 25)}
    for key, (month, day) in dates.items():
        created_at = datetime(2026, month, day, 12, tzinfo=UTC)
        await db_session.execute(update(Order).where(Order.id == orders[key]["id"]).values(created_at=created_at))
    await db_session.commit()
    await set_status(db_session, orders["alice_paid"]["id"], OrderStatusEnum.paid)
    await set_status(db_session, orders["bob_canceled"]["id"], OrderStatusEnum.canceled)
    return orders


def ids(response) -> list[int]:
    return [order["id"] for order in response.json()["orders"]]


async def test_admin_sees_all_orders_newest_first(client, db_session, catalog, alice, bob, admin_headers):
    orders = await make_orders(client, db_session, catalog, alice, bob)

    response = await client.get(ADMIN_ORDERS_URL, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert ids(response) == [orders["bob_canceled"]["id"], orders["alice_paid"]["id"], orders["alice_pending"]["id"]]
    assert body["orders"][0]["user_id"] == bob.id
    assert body["orders"][0]["status"] == "canceled"
    assert (body["total_items"], body["total_pages"], body["prev_page"], body["next_page"]) == (3, 1, None, None)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "paid"}, ["alice_paid"]),
        ({"date_from": "2026-02-01"}, ["bob_canceled", "alice_paid"]),
        ({"date_to": "2026-02-20"}, ["alice_paid", "alice_pending"]),
        ({"date_from": "2026-02-20", "date_to": "2026-02-20"}, ["alice_paid"]),
        ({"date_from": "2026-02-01", "status": "pending"}, []),
    ],
    ids=["status", "date-from", "date-to-inclusive", "one-day", "combined"],
)
async def test_admin_filters_orders(client, db_session, catalog, alice, bob, admin_headers, params, expected):
    orders = await make_orders(client, db_session, catalog, alice, bob)

    response = await client.get(ADMIN_ORDERS_URL, params=params, headers=admin_headers)

    assert response.status_code == 200
    assert ids(response) == [orders[key]["id"] for key in expected]
    assert response.json()["total_items"] == len(expected)


async def test_admin_filters_orders_by_user(client, db_session, catalog, alice, bob, admin_headers):
    orders = await make_orders(client, db_session, catalog, alice, bob)

    response = await client.get(ADMIN_ORDERS_URL, params={"user_id": alice.id}, headers=admin_headers)

    assert ids(response) == [orders["alice_paid"]["id"], orders["alice_pending"]["id"]]


async def test_admin_orders_are_paginated(client, db_session, catalog, alice, bob, admin_headers):
    orders = await make_orders(client, db_session, catalog, alice, bob)

    response = await client.get(ADMIN_ORDERS_URL, params={"page": 2, "per_page": 2}, headers=admin_headers)

    body = response.json()
    assert ids(response) == [orders["alice_pending"]["id"]]
    assert (body["total_items"], body["total_pages"], body["next_page"]) == (3, 2, None)
    prev = urlsplit(body["prev_page"])
    assert prev.path == ADMIN_ORDERS_URL
    assert parse_qs(prev.query) == {"page": ["1"], "per_page": ["2"]}


async def test_admin_page_links_keep_the_filters(client, db_session, catalog, alice, bob, admin_headers):
    await make_orders(client, db_session, catalog, alice, bob)

    response = await client.get(ADMIN_ORDERS_URL, params={"user_id": alice.id, "per_page": 1}, headers=admin_headers)

    next_page = parse_qs(urlsplit(response.json()["next_page"]).query)
    assert next_page == {"user_id": [str(alice.id)], "page": ["2"], "per_page": ["1"]}


@pytest.mark.parametrize(
    "params",
    [{"date_from": "2026-03-01", "date_to": "2026-02-01"}, {"status": "lost"}, {"page": 0}],
    ids=["dates-reversed", "unknown-status", "page-zero"],
)
async def test_admin_invalid_filters_give_422(client, admin_headers, params):
    response = await client.get(ADMIN_ORDERS_URL, params=params, headers=admin_headers)

    assert response.status_code == 422


@pytest.mark.parametrize("group", [UserGroupEnum.USER, UserGroupEnum.MODERATOR])
async def test_not_admin_cannot_see_all_orders(client, db_session, group):
    headers = await headers_for(client, db_session, group, "curious@example.com")

    response = await client.get(ADMIN_ORDERS_URL, headers=headers)

    assert response.status_code == 403


# --- cascade ---


async def test_deleting_a_user_removes_their_orders_only(client, db_session, catalog, alice, bob):
    await place_order(client, alice, catalog["The Matrix"])
    await place_order(client, bob, catalog["The Matrix"])

    await db_session.delete(await db_session.get(User, alice.id))
    await db_session.commit()

    assert list(await db_session.scalars(select(Order.user_id))) == [bob.id]
    assert (await db_session.execute(select(func.count()).select_from(OrderItem))).scalar_one() == 1


async def test_refund_needs_a_paid_order_even_with_a_payment(client, db_session, catalog, alice, payment_gateway):
    order = await place_order(client, alice, catalog["The Matrix"])
    await mark_paid(db_session, order["id"])
    await set_status(db_session, order["id"], OrderStatusEnum.canceled)

    response = await client.post(f"{ORDERS_URL}/{order['id']}/refund", headers=alice.headers)

    assert response.status_code == 409
    assert payment_gateway.refunds == []
