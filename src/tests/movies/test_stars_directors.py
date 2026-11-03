"""GET list (paginated, with movie counts) and GET details for stars and directors."""

import pytest
from sqlalchemy import insert, select, update

from src.movies.models import Director, Movie, Star, movie_directors_table, movie_stars_table
from src.tests.utils import DIRECTORS_URL, STARS_URL

ENTITIES = [
    pytest.param(
        STARS_URL,
        Star,
        movie_stars_table,
        "star_id",
        "stars",
        {"Keanu Reeves": 1, "Leonardo DiCaprio": 1, "Tom Hanks": 2},
        id="stars",
    ),
    pytest.param(
        DIRECTORS_URL,
        Director,
        movie_directors_table,
        "director_id",
        "directors",
        {"Christopher Nolan": 1, "Lana Wachowski": 1, "Robert Zemeckis": 2},
        id="directors",
    ),
]

pytestmark = pytest.mark.parametrize(("url", "model", "table", "column", "key", "counts"), ENTITIES)


async def test_list_on_empty_db(client, url, model, table, column, key, counts):
    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == {key: [], "total_items": 0, "total_pages": 0, "prev_page": None, "next_page": None}


async def test_list_is_ordered_by_name_and_counts_movies(
    client, db_session, catalog, url, model, table, column, key, counts
):
    db_session.add(model(name="Aaron Nobody"))
    await db_session.commit()

    response = await client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert [(item["name"], item["movies_count"]) for item in body[key]] == [("Aaron Nobody", 0), *counts.items()]
    ids = {name: record_id for name, record_id in await db_session.execute(select(model.name, model.id))}
    assert [item["id"] for item in body[key]] == [ids[item["name"]] for item in body[key]]
    assert (body["total_items"], body["total_pages"], body["prev_page"], body["next_page"]) == (4, 1, None, None)


async def test_list_pagination(client, catalog, url, model, table, column, key, counts):
    first = (await client.get(url, params={"page": 1, "per_page": 2})).json()
    second = (await client.get(url, params={"page": 2, "per_page": 2})).json()

    names = list(counts)
    assert [item["name"] for item in first[key]] == names[:2]
    assert [item["name"] for item in second[key]] == names[2:]
    assert (first["total_items"], first["total_pages"]) == (3, 2)
    assert first["prev_page"] is None
    assert first["next_page"] == f"{url}?page=2&per_page=2"
    assert second["prev_page"] == f"{url}?page=1&per_page=2"
    assert second["next_page"] is None


async def test_list_page_after_last_is_empty(client, catalog, url, model, table, column, key, counts):
    response = await client.get(url, params={"page": 5, "per_page": 2})

    assert response.status_code == 200
    assert response.json()[key] == []
    assert response.json()["total_items"] == 3


@pytest.mark.parametrize("params", [{"page": 0}, {"per_page": 0}, {"per_page": 10_000}, {"page": "x"}])
async def test_list_rejects_invalid_pagination(client, url, model, table, column, key, counts, params):
    response = await client.get(url, params=params)

    assert response.status_code == 422


async def test_details_lists_movies_ordered_by_id(client, db_session, catalog, url, model, table, column, key, counts):
    record = model(name="Everywhere")
    db_session.add(record)
    await db_session.commit()
    by_id_desc = sorted(catalog.values(), key=lambda movie: movie.id, reverse=True)
    for movie in by_id_desc:
        await db_session.execute(insert(table).values(movie_id=movie.id, **{column: record.id}))
    # An UPDATE moves the row to the end of the table, so without ORDER BY Postgres would return it last.
    first_id = by_id_desc[-1].id
    await db_session.execute(update(Movie).where(Movie.id == first_id).values(votes=Movie.votes + 1))
    await db_session.commit()

    response = await client.get(f"{url}/{record.id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["name"]) == (record.id, "Everywhere")
    assert [movie["id"] for movie in body["movies"]] == sorted(movie.id for movie in catalog.values())
    assert set(body["movies"][0]) == {"id", "name", "year", "time", "imdb", "votes", "description"}


async def test_details_unknown_returns_404(client, url, model, table, column, key, counts):
    response = await client.get(f"{url}/999")

    assert response.status_code == 404
    assert response.json() == {"detail": f"No {key[:-1]} with id:999 found."}
