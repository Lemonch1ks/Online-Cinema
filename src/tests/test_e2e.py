"""End-to-end user scenario: from registration to a purchased movie, only through the HTTP API.

Stripe is replaced by FakePaymentGateway and emails by FakeEmailSender; everything else is the real app and database.
"""

import pytest

from src.core.config import settings
from src.tests.conftest import FakePaymentGateway
from src.tests.movies.conftest import catalog  # noqa: F401  (shared fixture: the movies an admin has added)
from src.tests.payments.test_payments import WEBHOOK_URL, stripe_event
from src.tests.utils import LOGIN_URL, MOVIES_URL, REGISTER_URL, bearer

API = settings.API_VERSION_PREFIX
EMAIL = "viewer@example.com"
PASSWORD = "Str0ng!Passw0rd"


@pytest.mark.usefixtures("catalog")
async def test_new_user_registers_finds_a_movie_buys_it_and_can_get_a_refund(client, email_sender, payment_gateway):
    # Registration: an inactive account and an activation email.
    registered = await client.post(REGISTER_URL, json={"email": EMAIL, "password": PASSWORD})
    assert registered.status_code == 201, registered.text
    not_active_yet = await client.post(LOGIN_URL, data={"username": EMAIL, "password": PASSWORD})
    assert not_active_yet.status_code == 403

    [(recipient, activation_link)] = email_sender.activation_emails
    assert recipient == EMAIL
    activated = await client.get(activation_link.removeprefix(settings.APP_BASE_URL))
    assert activated.status_code == 200, activated.text

    # Login.
    tokens = await client.post(LOGIN_URL, data={"username": EMAIL, "password": PASSWORD})
    assert tokens.status_code == 200, tokens.text
    headers = bearer(tokens.json()["access_token"])

    # Filtering the catalog: only one movie is newer than 2005.
    found = await client.get(MOVIES_URL, params={"year_from": 2005})
    assert [movie["name"] for movie in found.json()["movies"]] == ["Inception"]
    movie_id = found.json()["movies"][0]["id"]

    # Cart and order.
    added = await client.post(f"{API}/cart/items", json={"movie_id": movie_id}, headers=headers)
    assert added.status_code == 201, added.text
    order = await client.post(f"{API}/orders", headers=headers)
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert (await client.get(f"{API}/cart", headers=headers)).json()["items"] == []

    # Payment: the user gets a Stripe page; Stripe confirms the payment through the webhook.
    checkout = await client.post(f"{API}/orders/{order_id}/pay", headers=headers)
    assert checkout.status_code == 200, checkout.text
    [(_, _, session)] = payment_gateway.sessions
    assert checkout.json() == {"checkout_url": session.url}
    payment_gateway.statuses[session.id] = "complete"
    webhook = await client.post(
        WEBHOOK_URL,
        content=stripe_event("checkout.session.completed", session.id, order_id, 749),
        headers={"Stripe-Signature": FakePaymentGateway.SIGNATURE},
    )
    assert webhook.status_code == 200, webhook.text

    # Confirmation on the site and by email; the movie is purchased and cannot be bought again.
    result = await client.get(f"{API}/payments/checkout/{session.id}", headers=headers)
    assert result.json()["result"] == "paid"
    assert email_sender.payment_success_emails == [(EMAIL, settings.PURCHASES_LINK_ENDPOINT)]
    purchases = await client.get(f"{API}/purchases", headers=headers)
    assert [(movie["name"], movie["price_paid"]) for movie in purchases.json()] == [("Inception", "7.49")]
    again = await client.post(f"{API}/cart/items", json={"movie_id": movie_id}, headers=headers)
    assert again.status_code == 409
    [payment] = (await client.get(f"{API}/payments", headers=headers)).json()
    assert (payment["status"], payment["amount"]) == ("successful", "7.49")

    # Refund: the money goes back, the order is canceled and the movie is no longer purchased.
    refunded = await client.post(f"{API}/orders/{order_id}/refund", headers=headers)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["status"] == "canceled"
    assert payment_gateway.refunds == ["pi_test_1"]
    assert (await client.get(f"{API}/purchases", headers=headers)).json() == []
    [payment] = (await client.get(f"{API}/payments", headers=headers)).json()
    assert payment["status"] == "refunded"
