import pytest

from src.core.config import settings
from src.tests.utils import MOVIES_URL


def names(response) -> list[str]:
    return [movie["name"] for movie in response.json()["movies"]]


# --- GET /movies: list and pagination ---

async def test_movies_list_on_empty_db_returns_404(client):
    response = await client.get(MOVIES_URL)

    assert response.status_code == 404


async def test_movies_list_returns_all_movies_ordered_by_id(client, catalog):
    response = await client.get(MOVIES_URL)

    assert response.status_code == 200
    body = response.json()
    assert names(response) == ["The Matrix", "Forrest Gump", "Cast Away", "Inception"]
    assert body["total_items"] == 4
    assert body["total_pages"] == 1
    assert body["prev_page"] is None
    assert body["next_page"] is None
    assert set(body["movies"][0]) == {"id", "name", "year", "time", "imdb", "votes", "description"}


async def test_movies_pagination_first_and_last_page(client, catalog):
    first = await client.get(MOVIES_URL, params={"page": 1, "per_page": 3})
    last = await client.get(MOVIES_URL, params={"page": 2, "per_page": 3})

    assert names(first) == ["The Matrix", "Forrest Gump", "Cast Away"]
    assert first.json()["total_pages"] == 2
    assert first.json()["prev_page"] is None
    assert first.json()["next_page"] == f"{MOVIES_URL}?page=2&per_page=3"

    assert names(last) == ["Inception"]
    assert last.json()["prev_page"] == f"{MOVIES_URL}?page=1&per_page=3"
    assert last.json()["next_page"] is None


async def test_movies_page_links_keep_filters(client, catalog):
    response = await client.get(MOVIES_URL, params={"year_from": 1990, "page": 1, "per_page": 1})

    assert response.json()["next_page"] == f"{MOVIES_URL}?year_from=1990&page=2&per_page=1"


async def test_movies_page_out_of_range_returns_404(client, catalog):
    response = await client.get(MOVIES_URL, params={"page": 3, "per_page": 2})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"per_page": 0},
        {"per_page": settings.PAGINATION_MAX_PER_PAGE + 1},
        {"imdb_from": -1},
        {"year_to": "last-year"},
        {"sort_by": "price"},
        {"order_type": "random"},
        {"search_param": ""},
        {"unknown_param": "x"},  # extra="forbid"
    ],
)
async def test_movies_invalid_query_returns_422(client, catalog, params):
    response = await client.get(MOVIES_URL, params=params)

    assert response.status_code == 422


# --- filters ---

@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"imdb_from": 8.7}, {"The Matrix", "Forrest Gump"}),
        ({"imdb_to": 8.0}, {"Cast Away"}),
        ({"year_from": 2000}, {"Cast Away", "Inception"}),
        ({"year_to": 1999}, {"The Matrix", "Forrest Gump"}),
        ({"year_from": 1995, "year_to": 2005}, {"The Matrix", "Cast Away"}),
        ({"meta_score_from": 80}, {"Forrest Gump", "Inception"}),
        ({"meta_score_to": 74}, {"The Matrix", "Cast Away"}),
        ({"gross_from": 250}, {"Forrest Gump", "Inception"}),
        ({"gross_to": 200}, {"The Matrix"}),
        ({"year_from": 1995, "imdb_from": 8.0}, {"The Matrix", "Inception"}),
    ],
)
async def test_movies_filters(client, catalog, params, expected):
    response = await client.get(MOVIES_URL, params=params)

    assert response.status_code == 200
    assert set(names(response)) == expected
    assert response.json()["total_items"] == len(expected)


async def test_movies_filter_without_matches_returns_404(client, catalog):
    response = await client.get(MOVIES_URL, params={"year_from": 2020})

    assert response.status_code == 404


# --- sorting ---

@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"sort_by": "year"}, ["Inception", "Cast Away", "The Matrix", "Forrest Gump"]),  # desc by default
        ({"sort_by": "year", "order_type": "asc"}, ["Forrest Gump", "The Matrix", "Cast Away", "Inception"]),
        ({"sort_by": "imdb", "order_type": "desc"}, ["Forrest Gump", "The Matrix", "Inception", "Cast Away"]),
        ({"sort_by": "meta_score", "order_type": "asc"}, ["The Matrix", "Cast Away", "Forrest Gump", "Inception"]),
        ({"sort_by": "gross", "order_type": "desc"}, ["Forrest Gump", "Inception", "Cast Away", "The Matrix"]),
        ({"order_type": "asc"}, ["The Matrix", "Forrest Gump", "Cast Away", "Inception"]),  # no sort_by: by id
    ],
)
async def test_movies_sorting(client, catalog, params, expected):
    response = await client.get(MOVIES_URL, params=params)

    assert names(response) == expected


async def test_movies_sorting_applies_before_pagination(client, catalog):
    response = await client.get(MOVIES_URL, params={"sort_by": "year", "page": 2, "per_page": 2})

    assert names(response) == ["The Matrix", "Forrest Gump"]


# --- search ---

@pytest.mark.parametrize(
    ("search", "expected"),
    [
        ("matrix", ["The Matrix"]),  # name, case-insensitive
        ("island", ["Cast Away"]),  # description
        ("keanu", ["The Matrix"]),  # star
        ("zemeckis", ["Forrest Gump", "Cast Away"]),  # director
        ("  inception  ", ["Inception"]),  # whitespace is stripped
        ("%", ["Inception"]),  # LIKE wildcards are escaped, "%" is a normal character
    ],
)
async def test_movies_search(client, catalog, search, expected):
    response = await client.get(MOVIES_URL, params={"search_param": search})

    assert response.status_code == 200
    assert names(response) == expected


async def test_movies_search_without_matches_returns_404(client, catalog):
    response = await client.get(MOVIES_URL, params={"search_param": "star wars"})

    assert response.status_code == 404


async def test_movies_search_filter_and_sort_combined(client, catalog):
    response = await client.get(
        MOVIES_URL, params={"search_param": "tom hanks", "year_from": 1990, "sort_by": "year", "order_type": "desc"}
    )

    assert names(response) == ["Cast Away", "Forrest Gump"]


# --- GET /movies/{movie_id} ---

async def test_movie_details(client, catalog):
    movie = catalog["The Matrix"]

    response = await client.get(f"{MOVIES_URL}/{movie.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == movie.id
    assert body["uuid"] == str(movie.uuid)
    assert body["name"] == "The Matrix"
    assert body["meta_score"] == 73
    assert body["gross"] == 171.5
    assert body["price"] == "9.99"
    assert body["certification_id"] == movie.certification_id
    assert [g["name"] for g in body["genres"]] == ["Action"]
    assert [s["name"] for s in body["stars"]] == ["Keanu Reeves"]
    assert [d["name"] for d in body["directors"]] == ["Lana Wachowski"]


async def test_movie_details_unknown_id_returns_404(client, catalog):
    response = await client.get(f"{MOVIES_URL}/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "No movies with id:9999 found."


async def test_movie_details_non_integer_id_returns_422(client):
    response = await client.get(f"{MOVIES_URL}/abc")

    assert response.status_code == 422
