"""Likes / dislikes and ratings of movies, their numbers in movie details, sorting by popularity."""

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from src.movies.models import MovieRating, MovieReaction
from src.tests.movies.conftest import make_member
from src.tests.utils import MOVIES_URL


def reaction_url(movie_id: int) -> str:
    return f"{MOVIES_URL}/{movie_id}/reaction"


def rating_url(movie_id: int) -> str:
    return f"{MOVIES_URL}/{movie_id}/rating"


async def reactions(db_session, movie_id: int) -> dict[int, bool]:
    stmt = select(MovieReaction.user_id, MovieReaction.is_like).where(MovieReaction.movie_id == movie_id)
    return {user_id: is_like for user_id, is_like in await db_session.execute(stmt)}


async def ratings(db_session, movie_id: int) -> dict[int, int]:
    stmt = select(MovieRating.user_id, MovieRating.score).where(MovieRating.movie_id == movie_id)
    return {user_id: score for user_id, score in await db_session.execute(stmt)}


async def details(client, movie_id: int) -> dict:
    response = await client.get(f"{MOVIES_URL}/{movie_id}")
    assert response.status_code == 200
    return response.json()


async def members(client, db_session, count: int) -> list:
    return [await make_member(client, db_session, f"fan{i}@example.com") for i in range(count)]


async def react(client, member, movie, is_like: bool) -> None:
    response = await client.put(reaction_url(movie.id), json={"is_like": is_like}, headers=member.headers)
    assert response.status_code == 200, response.text


# --- reactions ---


async def test_anonymous_gets_401(client, catalog):
    matrix = catalog["The Matrix"]

    responses = [
        await client.put(reaction_url(matrix.id), json={"is_like": True}),
        await client.delete(reaction_url(matrix.id)),
        await client.put(rating_url(matrix.id), json={"score": 5}),
        await client.delete(rating_url(matrix.id)),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]


async def test_like_is_saved(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]

    response = await client.put(reaction_url(matrix.id), json={"is_like": True}, headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == {"movie_id": matrix.id, "is_like": True}
    assert await reactions(db_session, matrix.id) == {alice.id: True}


async def test_dislike_replaces_like(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await react(client, alice, matrix, True)

    response = await client.put(reaction_url(matrix.id), json={"is_like": False}, headers=alice.headers)

    assert response.json() == {"movie_id": matrix.id, "is_like": False}
    assert await reactions(db_session, matrix.id) == {alice.id: False}
    movie = await details(client, matrix.id)
    assert (movie["likes"], movie["dislikes"]) == (0, 1)


async def test_remove_reaction(client, db_session, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    await react(client, alice, matrix, True)
    await react(client, bob, matrix, True)

    response = await client.delete(reaction_url(matrix.id), headers=alice.headers)
    again = await client.delete(reaction_url(matrix.id), headers=alice.headers)

    assert (response.status_code, again.status_code) == (204, 204)
    assert await reactions(db_session, matrix.id) == {bob.id: True}


@pytest.mark.parametrize("body", [{}, {"is_like": "yes"}, {"is_like": 1}, {"is_like": None}, {"is_like": True, "x": 1}])
async def test_invalid_reaction_returns_422(client, db_session, catalog, alice, body):
    matrix = catalog["The Matrix"]

    response = await client.put(reaction_url(matrix.id), json=body, headers=alice.headers)

    assert response.status_code == 422
    assert await reactions(db_session, matrix.id) == {}


async def test_reaction_on_unknown_movie_returns_404(client, alice):
    put = await client.put(reaction_url(999), json={"is_like": True}, headers=alice.headers)
    delete = await client.delete(reaction_url(999), headers=alice.headers)

    assert (put.status_code, delete.status_code) == (404, 404)
    assert put.json() == {"detail": "No movies with id:999 found."}


async def test_details_count_likes_and_dislikes_of_this_movie_only(client, db_session, catalog):
    matrix, gump = catalog["The Matrix"], catalog["Forrest Gump"]
    fans = await members(client, db_session, 4)
    for fan in fans[:3]:
        await react(client, fan, matrix, True)
    await react(client, fans[3], matrix, False)
    await react(client, fans[0], gump, False)

    matrix_details, gump_details = await details(client, matrix.id), await details(client, gump.id)

    assert (matrix_details["likes"], matrix_details["dislikes"]) == (3, 1)
    assert (gump_details["likes"], gump_details["dislikes"]) == (0, 1)


# --- ratings ---


async def test_rating_is_saved_and_can_be_changed(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]

    first = await client.put(rating_url(matrix.id), json={"score": 8}, headers=alice.headers)
    second = await client.put(rating_url(matrix.id), json={"score": 3}, headers=alice.headers)

    assert first.json() == {"movie_id": matrix.id, "score": 8}
    assert second.json() == {"movie_id": matrix.id, "score": 3}
    assert await ratings(db_session, matrix.id) == {alice.id: 3}


INVALID_RATINGS = [{}, {"score": 0}, {"score": 11}, {"score": 5.5}, {"score": "x"}, {"score": 5, "x": 1}]


@pytest.mark.parametrize("body", INVALID_RATINGS)
async def test_invalid_rating_returns_422(client, db_session, catalog, alice, body):
    matrix = catalog["The Matrix"]

    response = await client.put(rating_url(matrix.id), json=body, headers=alice.headers)

    assert response.status_code == 422
    assert await ratings(db_session, matrix.id) == {}


@pytest.mark.parametrize("score", [1, 10])
async def test_rating_bounds_are_allowed(client, db_session, catalog, alice, score):
    response = await client.put(rating_url(catalog["The Matrix"].id), json={"score": score}, headers=alice.headers)

    assert response.status_code == 200


async def test_database_rejects_score_out_of_range(db_session, catalog, alice):
    with pytest.raises(IntegrityError):
        await db_session.execute(
            insert(MovieRating).values(user_id=alice.id, movie_id=catalog["Inception"].id, score=11)
        )


async def test_remove_rating(client, db_session, catalog, alice):
    matrix = catalog["The Matrix"]
    await client.put(rating_url(matrix.id), json={"score": 8}, headers=alice.headers)

    response = await client.delete(rating_url(matrix.id), headers=alice.headers)

    assert response.status_code == 204
    assert await ratings(db_session, matrix.id) == {}


async def test_rating_on_unknown_movie_returns_404(client, alice):
    put = await client.put(rating_url(999), json={"score": 5}, headers=alice.headers)
    delete = await client.delete(rating_url(999), headers=alice.headers)

    assert (put.status_code, delete.status_code) == (404, 404)


async def test_details_without_activity(client, catalog):
    movie = await details(client, catalog["The Matrix"].id)

    assert (movie["likes"], movie["dislikes"], movie["rating_avg"], movie["rating_count"]) == (0, 0, None, 0)


@pytest.mark.parametrize(("scores", "average"), [([6, 9], 7.5), ([7, 8, 8], 7.67), ([10], 10.0)])
async def test_details_show_average_rating(client, db_session, catalog, scores, average):
    matrix, gump = catalog["The Matrix"], catalog["Forrest Gump"]
    fans = await members(client, db_session, len(scores))
    for fan, score in zip(fans, scores, strict=True):
        await client.put(rating_url(matrix.id), json={"score": score}, headers=fan.headers)
    await client.put(rating_url(gump.id), json={"score": 1}, headers=fans[0].headers)

    movie = await details(client, matrix.id)

    assert (movie["rating_avg"], movie["rating_count"]) == (average, len(scores))


# --- sorting by popularity (number of likes) ---


@pytest.fixture()
async def liked_catalog(client, db_session, catalog):
    """Inception: 2 likes; The Matrix: 1 like and 3 dislikes; Forrest Gump: none; Cast Away: 1 dislike."""
    fans = await members(client, db_session, 4)
    await react(client, fans[0], catalog["Inception"], True)
    await react(client, fans[1], catalog["Inception"], True)
    await react(client, fans[0], catalog["The Matrix"], True)
    for fan in fans[1:]:
        await react(client, fan, catalog["The Matrix"], False)
    await react(client, fans[0], catalog["Cast Away"], False)
    return catalog


def names(response) -> list[str]:
    return [movie["name"] for movie in response.json()["movies"]]


@pytest.mark.parametrize(
    ("order_type", "expected"),
    [
        ("desc", ["Inception", "The Matrix", "Forrest Gump", "Cast Away"]),
        ("asc", ["Forrest Gump", "Cast Away", "The Matrix", "Inception"]),
    ],
)
async def test_sort_by_popularity_counts_likes_only(client, liked_catalog, order_type, expected):
    response = await client.get(MOVIES_URL, params={"sort_by": "popularity", "order_type": order_type})

    assert response.status_code == 200
    assert names(response) == expected
    assert response.json()["total_items"] == 4


async def test_sort_by_popularity_with_filter_and_pagination(client, liked_catalog):
    params = {"sort_by": "popularity", "year_from": 1999, "per_page": 2}

    first = await client.get(MOVIES_URL, params=params)
    second = await client.get(MOVIES_URL, params={**params, "page": 2})

    assert names(first) == ["Inception", "The Matrix"]
    assert names(second) == ["Cast Away"]
    assert (first.json()["total_items"], first.json()["total_pages"]) == (3, 2)


async def test_favorites_can_be_sorted_by_popularity(client, liked_catalog, alice):
    for name in ("Cast Away", "Inception", "Forrest Gump"):
        await client.post(f"{MOVIES_URL}/{liked_catalog[name].id}/favorite", headers=alice.headers)

    response = await client.get("/api/v1/favorites", params={"sort_by": "popularity"}, headers=alice.headers)

    assert names(response) == ["Inception", "Forrest Gump", "Cast Away"]
    assert response.json()["total_items"] == 3
