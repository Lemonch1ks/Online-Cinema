from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select, update

from src.auth.models import User, UserGroupEnum
from src.core.config import settings
from src.movies.models import Favorite
from src.tests.movies.conftest import make_member
from src.tests.utils import MOVIES_URL

FAVORITES_URL = f"{settings.API_VERSION_PREFIX}/favorites"


def favorite_url(movie_id: int) -> str:
    return f"{MOVIES_URL}/{movie_id}/favorite"


def names(response) -> list[str]:
    return [movie["name"] for movie in response.json()["movies"]]


async def favorite_ids(db_session, user_id: int) -> list[int]:
    stmt = select(Favorite.movie_id).where(Favorite.user_id == user_id).order_by(Favorite.movie_id)
    return list(await db_session.scalars(stmt))


async def add(client, member, *movies) -> None:
    for movie in movies:
        response = await client.post(favorite_url(movie.id), headers=member.headers)
        assert response.status_code == 201, response.text


async def test_anonymous_gets_401(client, catalog):
    matrix = catalog["The Matrix"]

    responses = [
        await client.post(favorite_url(matrix.id)),
        await client.delete(favorite_url(matrix.id)),
        await client.get(FAVORITES_URL),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]


async def test_inactive_user_gets_403(client, db_session, catalog):
    member = await make_member(client, db_session, "sleepy@example.com")
    await db_session.execute(update(User).where(User.id == member.id).values(is_active=False))
    await db_session.commit()

    response = await client.post(favorite_url(catalog["The Matrix"].id), headers=member.headers)

    assert response.status_code == 403
    assert await favorite_ids(db_session, member.id) == []


async def test_add_favorite_saves_it(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]

    response = await client.post(favorite_url(matrix.id), headers=alice.headers)

    assert response.status_code == 201
    assert response.json() == {"movie_id": matrix.id}
    assert await favorite_ids(db_session, alice.id) == [matrix.id]


async def test_adding_twice_returns_200_and_keeps_one_row(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await add(client, alice, matrix)

    response = await client.post(favorite_url(matrix.id), headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == {"movie_id": matrix.id}
    assert await favorite_ids(db_session, alice.id) == [matrix.id]


async def test_add_unknown_movie_returns_404(client, db_session, alice):
    response = await client.post(favorite_url(999), headers=alice.headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "No movies with id:999 found."}
    assert await favorite_ids(db_session, alice.id) == []


async def test_remove_favorite(client, db_session, catalog, alice):
    matrix, gump = catalog["The Matrix"], catalog["Forrest Gump"]
    await add(client, alice, matrix, gump)

    response = await client.delete(favorite_url(matrix.id), headers=alice.headers)

    assert response.status_code == 204
    assert await favorite_ids(db_session, alice.id) == [gump.id]


async def test_remove_movie_that_is_not_in_favorites_returns_204(client, db_session, catalog, alice):
    response = await client.delete(favorite_url(catalog["The Matrix"].id), headers=alice.headers)

    assert response.status_code == 204


async def test_remove_unknown_movie_returns_404(client, alice):
    response = await client.delete(favorite_url(999), headers=alice.headers)

    assert response.status_code == 404


async def test_users_do_not_see_or_remove_each_others_favorites(client, db_session, catalog, alice, bob):
    matrix, gump = catalog["The Matrix"], catalog["Forrest Gump"]
    await add(client, alice, matrix)
    await add(client, bob, gump)

    alice_list = await client.get(FAVORITES_URL, headers=alice.headers)
    await client.delete(favorite_url(gump.id), headers=alice.headers)

    assert names(alice_list) == ["The Matrix"]
    assert alice_list.json()["total_items"] == 1
    assert await favorite_ids(db_session, bob.id) == [gump.id]


async def test_empty_favorites(client, catalog, alice):
    response = await client.get(FAVORITES_URL, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == {"movies": [], "total_items": 0, "total_pages": 0, "prev_page": None, "next_page": None}


async def test_favorites_support_search_filters_and_sorting(client, catalog, alice):
    await add(client, alice, *catalog.values())

    by_price = await client.get(FAVORITES_URL, params={"sort_by": "price", "order_type": "asc"}, headers=alice.headers)
    filtered = await client.get(FAVORITES_URL, params={"year_from": 2000}, headers=alice.headers)
    searched = await client.get(FAVORITES_URL, params={"search_param": "tom hanks"}, headers=alice.headers)

    assert names(by_price) == ["Forrest Gump", "Inception", "The Matrix", "Cast Away"]
    assert names(filtered) == ["Cast Away", "Inception"]
    assert names(searched) == ["Forrest Gump", "Cast Away"]


async def test_favorites_pagination_links_point_to_favorites(client, catalog, alice):
    await add(client, alice, catalog["The Matrix"], catalog["Inception"])

    response = await client.get(FAVORITES_URL, params={"per_page": 1}, headers=alice.headers)

    body = response.json()
    assert (body["total_items"], body["total_pages"]) == (2, 2)
    next_page = urlsplit(body["next_page"])
    assert next_page.path == FAVORITES_URL
    assert parse_qs(next_page.query) == {"page": ["2"], "per_page": ["1"]}


async def test_favorites_reject_invalid_query(client, alice):
    response = await client.get(FAVORITES_URL, params={"sort_by": "title"}, headers=alice.headers)

    assert response.status_code == 422


async def test_moderator_can_use_favorites_too(client, db_session, catalog):
    moderator = await make_member(client, db_session, "mod@example.com", UserGroupEnum.MODERATOR)

    response = await client.post(favorite_url(catalog["The Matrix"].id), headers=moderator.headers)

    assert response.status_code == 201
