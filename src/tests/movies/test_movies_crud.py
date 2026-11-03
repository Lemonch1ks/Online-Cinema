from decimal import Decimal

import pytest
from sqlalchemy import func, select

from src.auth.models import UserGroupEnum
from src.movies.models import (
    Certification,
    Director,
    Genre,
    Movie,
    Star,
    movie_directors_table,
    movie_genres_table,
    movie_stars_table,
)
from src.tests.utils import MOVIES_URL, bearer, create_user_in_group, login

MODERATOR_EMAIL = "moderator@example.com"

NEW_MOVIE = {
    "name": "Interstellar",
    "year": 2014,
    "time": 169,
    "imdb": 8.7,
    "votes": 2000000,
    "meta_score": 74,
    "gross": 188.0,
    "price": "12.50",
    "description": "A team travels through a wormhole.",
    "certification": "PG-13",
    "genres": ["Sci-Fi", "Drama"],
    "stars": ["Matthew McConaughey"],
    "directors": ["Christopher Nolan"],
}


def movie_url(movie_id: int) -> str:
    return f"{MOVIES_URL}/{movie_id}"


async def headers_for(client, db_session, group: UserGroupEnum, email: str = MODERATOR_EMAIL) -> dict:
    await create_user_in_group(db_session, email, group)
    return bearer((await login(client, email))["access_token"])


@pytest.fixture()
async def moderator_headers(client, db_session) -> dict:
    return await headers_for(client, db_session, UserGroupEnum.MODERATOR)


async def count(db_session, model) -> int:
    return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()


async def names_of(db_session, model) -> list[str]:
    return list(await db_session.scalars(select(model.name).order_by(model.name)))


async def linked_names(db_session, movie_id: int) -> dict[str, list[str]]:
    """Relations of a movie read straight from the association tables."""
    result = {}
    for key, table, model, column in (
        ("genres", movie_genres_table, Genre, "genre_id"),
        ("stars", movie_stars_table, Star, "star_id"),
        ("directors", movie_directors_table, Director, "director_id"),
    ):
        stmt = (
            select(model.name)
            .join(table, table.c[column] == model.id)
            .where(table.c.movie_id == movie_id)
            .order_by(model.name)
        )
        result[key] = list(await db_session.scalars(stmt))
    return result


async def movie_row(db_session, movie_id: int) -> dict | None:
    stmt = select(Movie.__table__).where(Movie.id == movie_id)
    row = (await db_session.execute(stmt)).mappings().one_or_none()
    return dict(row) if row else None


async def certification_name(db_session, movie_id: int) -> str:
    stmt = select(Certification.name).join(Movie).where(Movie.id == movie_id)
    return (await db_session.execute(stmt)).scalar_one()


# --- access control ---


async def test_anonymous_cannot_change_movies(client, db_session, catalog):
    matrix = catalog["The Matrix"]

    responses = [
        await client.post(MOVIES_URL, json=NEW_MOVIE),
        await client.patch(movie_url(matrix.id), json={"price": "1.00"}),
        await client.delete(movie_url(matrix.id)),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert await count(db_session, Movie) == len(catalog)
    assert (await movie_row(db_session, matrix.id))["price"] == Decimal("9.99")


async def test_regular_user_gets_403(client, db_session, catalog):
    headers = await headers_for(client, db_session, UserGroupEnum.USER, "user@example.com")
    matrix = catalog["The Matrix"]

    responses = [
        await client.post(MOVIES_URL, json=NEW_MOVIE, headers=headers),
        await client.patch(movie_url(matrix.id), json={"price": "1.00"}, headers=headers),
        await client.delete(movie_url(matrix.id), headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert await count(db_session, Movie) == len(catalog)
    assert (await movie_row(db_session, matrix.id))["price"] == Decimal("9.99")


@pytest.mark.parametrize("group", [UserGroupEnum.MODERATOR, UserGroupEnum.ADMIN])
async def test_moderator_and_admin_can_create_movie(client, db_session, group):
    headers = await headers_for(client, db_session, group)

    response = await client.post(MOVIES_URL, json=NEW_MOVIE, headers=headers)

    assert response.status_code == 201, response.text
    assert await count(db_session, Movie) == 1


# --- POST /movies ---


async def test_create_movie_returns_it_and_saves_relations(client, db_session, moderator_headers):
    response = await client.post(MOVIES_URL, json=NEW_MOVIE, headers=moderator_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    movie_id = body["id"]
    row = await movie_row(db_session, movie_id)
    assert row is not None
    assert body["uuid"] == str(row["uuid"])
    assert body["certification_id"] == row["certification_id"]
    for field in ("name", "year", "time", "imdb", "votes", "meta_score", "gross", "description"):
        assert body[field] == NEW_MOVIE[field] == row[field]
    assert Decimal(body["price"]) == row["price"] == Decimal("12.50")
    assert sorted(genre["name"] for genre in body["genres"]) == ["Drama", "Sci-Fi"]
    assert [star["name"] for star in body["stars"]] == ["Matthew McConaughey"]
    assert [director["name"] for director in body["directors"]] == ["Christopher Nolan"]

    assert await linked_names(db_session, movie_id) == {
        "genres": ["Drama", "Sci-Fi"],
        "stars": ["Matthew McConaughey"],
        "directors": ["Christopher Nolan"],
    }
    assert await certification_name(db_session, movie_id) == "PG-13"


async def test_create_movie_is_visible_in_movie_details(client, moderator_headers):
    created = (await client.post(MOVIES_URL, json=NEW_MOVIE, headers=moderator_headers)).json()

    details = await client.get(movie_url(created["id"]))

    assert details.status_code == 200
    assert details.json() == created


async def test_create_reuses_existing_names_ignoring_case(client, db_session, catalog, moderator_headers):
    genres_before = await count(db_session, Genre)
    payload = {
        **NEW_MOVIE,
        "certification": "pg-13",
        "genres": ["drama", "ACTION"],
        "stars": ["tom hanks"],
        "directors": ["christopher nolan"],
    }

    response = await client.post(MOVIES_URL, json=payload, headers=moderator_headers)

    assert response.status_code == 201, response.text
    assert await count(db_session, Genre) == genres_before
    assert await count(db_session, Star) == 3
    assert await count(db_session, Director) == 3
    assert await count(db_session, Certification) == 1
    assert await linked_names(db_session, response.json()["id"]) == {
        "genres": ["Action", "Drama"],
        "stars": ["Tom Hanks"],
        "directors": ["Christopher Nolan"],
    }


async def test_create_strips_names_and_drops_duplicates(client, db_session, moderator_headers):
    payload = {**NEW_MOVIE, "genres": ["Drama", " drama ", "Sci-Fi"], "stars": ["  Anne Hathaway "]}

    response = await client.post(MOVIES_URL, json=payload, headers=moderator_headers)

    assert response.status_code == 201, response.text
    assert await names_of(db_session, Genre) == ["Drama", "Sci-Fi"]
    assert await linked_names(db_session, response.json()["id"]) == {
        "genres": ["Drama", "Sci-Fi"],
        "stars": ["Anne Hathaway"],
        "directors": ["Christopher Nolan"],
    }


async def test_create_with_only_required_fields(client, db_session, moderator_headers):
    payload = {key: NEW_MOVIE[key] for key in ("name", "year", "time", "imdb", "votes", "price", "description")}
    payload["certification"] = "R"

    response = await client.post(MOVIES_URL, json=payload, headers=moderator_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["meta_score"], body["gross"], body["genres"], body["stars"], body["directors"]) == (
        None,
        None,
        [],
        [],
        [],
    )
    assert await certification_name(db_session, body["id"]) == "R"


async def test_create_duplicate_movie_returns_409_and_changes_nothing(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]
    genres_before = await names_of(db_session, Genre)
    payload = {**NEW_MOVIE, "name": matrix.name, "year": matrix.year, "time": matrix.time, "genres": ["Western"]}

    response = await client.post(MOVIES_URL, json=payload, headers=moderator_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "A movie with this name, year and time already exists."}
    assert await count(db_session, Movie) == len(catalog)
    assert await names_of(db_session, Genre) == genres_before


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": "   "},
        {"name": None},
        {"year": 1700},
        {"time": 0},
        {"imdb": 10.5},
        {"imdb": -1},
        {"votes": -1},
        {"meta_score": 101},
        {"gross": -1},
        {"price": "-1.00"},
        {"price": "1.234"},
        {"price": "123456789.00"},
        {"description": ""},
        {"certification": ""},
        {"genres": [""]},
        {"genres": "Drama"},
        {"unknown_field": 1},
    ],
    ids=str,
)
async def test_create_rejects_invalid_data(client, db_session, moderator_headers, changes):
    response = await client.post(MOVIES_URL, json={**NEW_MOVIE, **changes}, headers=moderator_headers)

    assert response.status_code == 422
    assert await count(db_session, Movie) == 0


@pytest.mark.parametrize("missing", ["name", "year", "time", "imdb", "votes", "price", "description", "certification"])
async def test_create_requires_field(client, db_session, moderator_headers, missing):
    payload = {key: value for key, value in NEW_MOVIE.items() if key != missing}

    response = await client.post(MOVIES_URL, json=payload, headers=moderator_headers)

    assert response.status_code == 422
    assert await count(db_session, Movie) == 0


# --- PATCH /movies/{id} ---


async def test_patch_changes_only_passed_fields(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]
    before = await movie_row(db_session, matrix.id)
    links_before = await linked_names(db_session, matrix.id)

    response = await client.patch(movie_url(matrix.id), json={"price": "4.99", "imdb": 9.1}, headers=moderator_headers)

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["price"]) == Decimal("4.99")
    assert response.json()["imdb"] == 9.1
    after = await movie_row(db_session, matrix.id)
    assert after == {**before, "price": Decimal("4.99"), "imdb": 9.1}
    assert await linked_names(db_session, matrix.id) == links_before


async def test_patch_response_matches_movie_details(client, catalog, moderator_headers):
    matrix = catalog["The Matrix"]

    response = await client.patch(movie_url(matrix.id), json={"genres": ["Sci-Fi"]}, headers=moderator_headers)

    assert response.json() == (await client.get(movie_url(matrix.id))).json()


async def test_patch_replaces_relations_and_keeps_old_records(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]

    response = await client.patch(
        movie_url(matrix.id),
        json={"genres": ["Sci-Fi", "action"], "stars": ["Carrie-Anne Moss"]},
        headers=moderator_headers,
    )

    assert response.status_code == 200, response.text
    assert await linked_names(db_session, matrix.id) == {
        "genres": ["Action", "Sci-Fi"],
        "stars": ["Carrie-Anne Moss"],
        "directors": ["Lana Wachowski"],
    }
    assert "Keanu Reeves" in await names_of(db_session, Star)


async def test_patch_with_empty_list_removes_all_relations(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]

    response = await client.patch(movie_url(matrix.id), json={"genres": []}, headers=moderator_headers)

    assert response.status_code == 200, response.text
    assert response.json()["genres"] == []
    assert (await linked_names(db_session, matrix.id))["genres"] == []
    assert "Action" in await names_of(db_session, Genre)


async def test_patch_changes_certification_by_name(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]

    response = await client.patch(movie_url(matrix.id), json={"certification": "R"}, headers=moderator_headers)

    assert response.status_code == 200, response.text
    assert await certification_name(db_session, matrix.id) == "R"
    assert response.json()["certification_id"] == (await movie_row(db_session, matrix.id))["certification_id"]
    assert await certification_name(db_session, catalog["Inception"].id) == "PG-13"


async def test_patch_can_clear_optional_fields(client, db_session, catalog, moderator_headers):
    matrix = catalog["The Matrix"]

    response = await client.patch(
        movie_url(matrix.id), json={"meta_score": None, "gross": None}, headers=moderator_headers
    )

    assert response.status_code == 200, response.text
    row = await movie_row(db_session, matrix.id)
    assert (row["meta_score"], row["gross"]) == (None, None)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": None},
        {"price": None},
        {"certification": None},
        {"genres": None},
        {"imdb": 11},
        {"genres": [" "]},
        {"unknown_field": 1},
    ],
    ids=str,
)
async def test_patch_rejects_invalid_data_and_changes_nothing(client, db_session, catalog, moderator_headers, changes):
    matrix = catalog["The Matrix"]
    before = await movie_row(db_session, matrix.id)
    links_before = await linked_names(db_session, matrix.id)

    response = await client.patch(movie_url(matrix.id), json=changes, headers=moderator_headers)

    assert response.status_code == 422
    assert await movie_row(db_session, matrix.id) == before
    assert await linked_names(db_session, matrix.id) == links_before


async def test_patch_into_duplicate_returns_409_and_changes_nothing(client, db_session, catalog, moderator_headers):
    matrix, gump = catalog["The Matrix"], catalog["Forrest Gump"]
    before = await movie_row(db_session, matrix.id)

    response = await client.patch(
        movie_url(matrix.id), json={"name": gump.name, "year": gump.year}, headers=moderator_headers
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "A movie with this name, year and time already exists."}
    assert await movie_row(db_session, matrix.id) == before


async def test_patch_unknown_movie_returns_404(client, moderator_headers):
    response = await client.patch(movie_url(999), json={"price": "1.00"}, headers=moderator_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "No movies with id:999 found."}


# --- DELETE /movies/{id} ---


async def test_delete_removes_movie_and_its_links_only(client, db_session, catalog, moderator_headers):
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    genres, stars, directors = [await names_of(db_session, model) for model in (Genre, Star, Director)]

    response = await client.delete(movie_url(matrix.id), headers=moderator_headers)

    assert response.status_code == 204
    assert response.content == b""
    assert await movie_row(db_session, matrix.id) is None
    assert await linked_names(db_session, matrix.id) == {"genres": [], "stars": [], "directors": []}
    assert await names_of(db_session, Genre) == genres
    assert await names_of(db_session, Star) == stars
    assert await names_of(db_session, Director) == directors
    assert (await linked_names(db_session, inception.id))["genres"] == ["Action"]
    assert (await client.get(movie_url(matrix.id))).status_code == 404


async def test_delete_unknown_movie_returns_404(client, db_session, catalog, moderator_headers):
    response = await client.delete(movie_url(999), headers=moderator_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "No movies with id:999 found."}
    assert await count(db_session, Movie) == len(catalog)
