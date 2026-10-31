from sqlalchemy import select

from src.movies.models import Genre
from src.tests.utils import GENRES_URL


async def test_genres_list_is_empty_on_fresh_db(client):
    response = await client.get(GENRES_URL)

    assert response.status_code == 200
    assert response.json() == {"genres": []}


async def test_genres_list_counts_movies_including_empty_genres(client, catalog):
    response = await client.get(GENRES_URL)

    assert response.status_code == 200
    counts = {genre["name"]: genre["movies_count"] for genre in response.json()["genres"]}
    assert counts == {"Action": 2, "Drama": 2, "Comedy": 0}


async def test_genres_list_is_ordered_by_id(client, db_session, catalog):
    expected_ids = (await db_session.execute(select(Genre.id).order_by(Genre.id))).scalars().all()

    response = await client.get(GENRES_URL)

    assert [genre["id"] for genre in response.json()["genres"]] == expected_ids


async def test_genre_details_lists_its_movies(client, db_session, catalog):
    drama = (await db_session.execute(select(Genre).where(Genre.name == "Drama"))).scalar_one()

    response = await client.get(f"{GENRES_URL}/{drama.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Drama"
    assert {movie["name"] for movie in body["movies"]} == {"Forrest Gump", "Cast Away"}


async def test_genre_details_without_movies(client, db_session, catalog):
    comedy = (await db_session.execute(select(Genre).where(Genre.name == "Comedy"))).scalar_one()

    response = await client.get(f"{GENRES_URL}/{comedy.id}")

    assert response.status_code == 200
    assert response.json()["movies"] == []


async def test_genre_details_unknown_id_returns_404(client):
    response = await client.get(f"{GENRES_URL}/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "No genre with id:9999 found."
