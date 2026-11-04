import pytest
from sqlalchemy import func, select, update

from src.auth.models import User, UserGroupEnum
from src.cart.models import Cart, CartItem
from src.core.config import settings
from src.movies.models import Movie
from src.tests.movies.conftest import make_member
from src.tests.utils import MOVIES_URL, headers_for

CART_URL = f"{settings.API_VERSION_PREFIX}/cart"
CART_ITEMS_URL = f"{CART_URL}/items"
ADMIN_CARTS_URL = f"{settings.API_VERSION_PREFIX}/admins/carts"
EMPTY_CART = {"items": [], "total_price": "0.00"}


async def cart_movie_ids(db_session, user_id: int) -> list[int]:
    stmt = (
        select(CartItem.movie_id)
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(Cart.user_id == user_id)
        .order_by(CartItem.movie_id)
    )
    return list(await db_session.scalars(stmt))


async def count(db_session, model) -> int:
    return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()


async def add(client, member, *movies) -> None:
    for movie in movies:
        response = await client.post(CART_ITEMS_URL, json={"movie_id": movie.id}, headers=member.headers)
        assert response.status_code == 201, response.text


def names(response) -> list[str]:
    return [item["name"] for item in response.json()["items"]]


# --- access ---


async def test_anonymous_gets_401(client, catalog):
    matrix = catalog["The Matrix"]

    responses = [
        await client.get(CART_URL),
        await client.post(CART_ITEMS_URL, json={"movie_id": matrix.id}),
        await client.delete(f"{CART_ITEMS_URL}/{matrix.id}"),
        await client.delete(CART_URL),
        await client.get(f"{ADMIN_CARTS_URL}/1"),
    ]

    assert [response.status_code for response in responses] == [401] * 5


async def test_inactive_user_gets_403(client, db_session, catalog):
    member = await make_member(client, db_session, "sleepy@example.com")
    await db_session.execute(update(User).where(User.id == member.id).values(is_active=False))
    await db_session.commit()

    response = await client.post(CART_ITEMS_URL, json={"movie_id": catalog["The Matrix"].id}, headers=member.headers)

    assert response.status_code == 403
    assert await cart_movie_ids(db_session, member.id) == []


# --- add ---


async def test_add_movie_saves_it_and_returns_the_item(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]

    response = await client.post(CART_ITEMS_URL, json={"movie_id": matrix.id}, headers=alice.headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "movie_id": matrix.id,
        "name": "The Matrix",
        "price": "9.99",
        "year": 1999,
        "genres": ["Action"],
        "added_at": body["added_at"],
    }
    assert body["added_at"]
    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]


async def test_user_has_one_cart_for_all_items(client, db_session, catalog, alice):
    await add(client, alice, catalog["The Matrix"], catalog["Inception"])

    assert await count(db_session, Cart) == 1
    assert await cart_movie_ids(db_session, alice.id) == sorted([catalog["The Matrix"].id, catalog["Inception"].id])


async def test_adding_the_same_movie_twice_gives_409(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await add(client, alice, matrix)

    response = await client.post(CART_ITEMS_URL, json={"movie_id": matrix.id}, headers=alice.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == f"Movie with id:{matrix.id} is already in the cart."
    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]


async def test_same_movie_in_carts_of_different_users(client, db_session, catalog, alice, bob):
    matrix = catalog["The Matrix"]

    await add(client, alice, matrix)
    await add(client, bob, matrix)

    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]
    assert await cart_movie_ids(db_session, bob.id) == [matrix.id]


async def test_add_unknown_movie_gives_404(client, db_session, catalog, alice):
    response = await client.post(CART_ITEMS_URL, json={"movie_id": 999_999}, headers=alice.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "No movies with id:999999 found."
    assert await count(db_session, CartItem) == 0


@pytest.mark.parametrize(
    "body",
    [{}, {"movie_id": "abc"}, {"movie_id": 1, "extra": True}],
    ids=["missing", "not-an-int", "extra-field"],
)
async def test_add_with_invalid_body_gives_422(client, db_session, catalog, alice, body):
    response = await client.post(CART_ITEMS_URL, json=body, headers=alice.headers)

    assert response.status_code == 422
    assert await count(db_session, CartItem) == 0


# --- view ---


async def test_new_user_sees_an_empty_cart(client, alice):
    response = await client.get(CART_URL, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == EMPTY_CART


async def test_cart_lists_items_in_the_order_they_were_added_with_total(client, catalog, alice):
    await add(client, alice, catalog["Inception"], catalog["The Matrix"], catalog["Cast Away"])

    response = await client.get(CART_URL, headers=alice.headers)

    assert response.status_code == 200
    assert names(response) == ["Inception", "The Matrix", "Cast Away"]
    item = response.json()["items"][0]
    assert item == {
        "movie_id": catalog["Inception"].id,
        "name": "Inception",
        "price": "7.49",
        "year": 2010,
        "genres": ["Action"],
        "added_at": item["added_at"],
    }
    assert response.json()["total_price"] == "32.47"


async def test_users_see_only_their_own_cart(client, catalog, alice, bob):
    await add(client, alice, catalog["The Matrix"])
    await add(client, bob, catalog["Forrest Gump"])

    alice_cart = await client.get(CART_URL, headers=alice.headers)
    bob_cart = await client.get(CART_URL, headers=bob.headers)

    assert names(alice_cart) == ["The Matrix"]
    assert alice_cart.json()["total_price"] == "9.99"
    assert names(bob_cart) == ["Forrest Gump"]


# --- remove and clear ---


async def test_remove_movie_deletes_only_this_item_of_this_user(client, db_session, catalog, alice, bob):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await add(client, alice, matrix, inception)
    await add(client, bob, matrix)

    response = await client.delete(f"{CART_ITEMS_URL}/{matrix.id}", headers=alice.headers)

    assert response.status_code == 204
    assert await cart_movie_ids(db_session, alice.id) == [inception.id]
    assert await cart_movie_ids(db_session, bob.id) == [matrix.id]


async def test_remove_movie_that_is_not_in_the_cart_gives_404(client, db_session, catalog, alice, bob):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await add(client, alice, inception)
    await add(client, bob, matrix)

    response = await client.delete(f"{CART_ITEMS_URL}/{matrix.id}", headers=alice.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == f"Movie with id:{matrix.id} is not in the cart."
    assert await cart_movie_ids(db_session, alice.id) == [inception.id]
    assert await cart_movie_ids(db_session, bob.id) == [matrix.id]


async def test_clear_cart_removes_all_items_of_this_user_only(client, db_session, catalog, alice, bob):
    await add(client, alice, catalog["The Matrix"], catalog["Inception"])
    await add(client, bob, catalog["The Matrix"])

    response = await client.delete(CART_URL, headers=alice.headers)

    assert response.status_code == 204
    assert await cart_movie_ids(db_session, alice.id) == []
    assert await cart_movie_ids(db_session, bob.id) == [catalog["The Matrix"].id]
    assert (await client.get(CART_URL, headers=alice.headers)).json() == EMPTY_CART


async def test_clear_cart_without_a_cart_gives_204(client, alice):
    response = await client.delete(CART_URL, headers=alice.headers)

    assert response.status_code == 204


# --- admin ---


async def test_admin_sees_a_users_cart(client, db_session, catalog, alice):
    await add(client, alice, catalog["The Matrix"], catalog["Forrest Gump"])
    admin = await headers_for(client, db_session, UserGroupEnum.ADMIN, "admin@example.com")

    response = await client.get(f"{ADMIN_CARTS_URL}/{alice.id}", headers=admin)

    assert response.status_code == 200
    assert names(response) == ["The Matrix", "Forrest Gump"]
    assert response.json()["total_price"] == "14.98"


async def test_admin_sees_an_empty_cart_of_a_user_without_one(client, db_session, alice):
    admin = await headers_for(client, db_session, UserGroupEnum.ADMIN, "admin@example.com")

    response = await client.get(f"{ADMIN_CARTS_URL}/{alice.id}", headers=admin)

    assert response.status_code == 200
    assert response.json() == EMPTY_CART


async def test_admin_gets_404_for_unknown_user(client, db_session):
    admin = await headers_for(client, db_session, UserGroupEnum.ADMIN, "admin@example.com")

    response = await client.get(f"{ADMIN_CARTS_URL}/999999", headers=admin)

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.parametrize("group", [UserGroupEnum.USER, UserGroupEnum.MODERATOR])
async def test_not_admin_cannot_see_other_carts(client, db_session, catalog, alice, group):
    await add(client, alice, catalog["The Matrix"])
    headers = await headers_for(client, db_session, group, "curious@example.com")

    response = await client.get(f"{ADMIN_CARTS_URL}/{alice.id}", headers=headers)

    assert response.status_code == 403
    assert "items" not in response.json()


# --- deleting a movie that is in carts ---


async def test_deleting_a_movie_in_carts_without_force_gives_409(
    client, db_session, catalog, alice, bob, moderator_headers
):
    matrix = catalog["The Matrix"]
    await add(client, alice, matrix)
    await add(client, bob, matrix)

    response = await client.delete(f"{MOVIES_URL}/{matrix.id}", headers=moderator_headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "The movie is in 2 users' carts. Pass force=true to delete it anyway."
    assert await db_session.scalar(select(Movie.id).where(Movie.id == matrix.id)) == matrix.id
    assert await cart_movie_ids(db_session, alice.id) == [matrix.id]
    assert await cart_movie_ids(db_session, bob.id) == [matrix.id]


async def test_deleting_a_movie_in_carts_with_force_removes_it_from_carts(
    client, db_session, catalog, alice, moderator_headers
):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await add(client, alice, matrix, inception)

    response = await client.delete(f"{MOVIES_URL}/{matrix.id}", params={"force": "true"}, headers=moderator_headers)

    assert response.status_code == 204
    assert await db_session.scalar(select(Movie.id).where(Movie.id == matrix.id)) is None
    assert await cart_movie_ids(db_session, alice.id) == [inception.id]


async def test_deleting_a_movie_not_in_carts_needs_no_force(client, db_session, catalog, alice, moderator_headers):
    await add(client, alice, catalog["Inception"])
    matrix = catalog["The Matrix"]

    response = await client.delete(f"{MOVIES_URL}/{matrix.id}", headers=moderator_headers)

    assert response.status_code == 204
    assert await db_session.scalar(select(Movie.id).where(Movie.id == matrix.id)) is None
    assert await cart_movie_ids(db_session, alice.id) == [catalog["Inception"].id]


async def test_deleting_an_unknown_movie_with_force_gives_404(client, catalog, moderator_headers):
    response = await client.delete(f"{MOVIES_URL}/999999", params={"force": "true"}, headers=moderator_headers)

    assert response.status_code == 404


# --- cascade ---


async def test_deleting_a_user_removes_their_cart_only(client, db_session, catalog, alice, bob):
    await add(client, alice, catalog["The Matrix"])
    await add(client, bob, catalog["The Matrix"])

    await db_session.delete(await db_session.get(User, alice.id))
    await db_session.commit()

    assert await db_session.scalar(select(Cart.id).where(Cart.user_id == alice.id)) is None
    assert await count(db_session, CartItem) == 1
    assert await cart_movie_ids(db_session, bob.id) == [catalog["The Matrix"].id]
