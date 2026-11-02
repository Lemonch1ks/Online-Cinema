from sqlalchemy import insert, select, update

from src.movies.models import Genre, Movie, movie_genres_table
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


async def test_genre_details_lists_movies_ordered_by_id(client, db_session, catalog):
    genre = Genre(name="Favourites")
    db_session.add(genre)
    await db_session.commit()
    movies_by_id_desc = sorted(catalog.values(), key=lambda movie: movie.id, reverse=True)
    for movie in movies_by_id_desc:
        await db_session.execute(insert(movie_genres_table).values(movie_id=movie.id, genre_id=genre.id))
    first_id = movies_by_id_desc[-1].id
    await db_session.execute(update(Movie).where(Movie.id == first_id).values(votes=Movie.votes + 1))
    await db_session.commit()

    response = await client.get(f"{GENRES_URL}/{genre.id}")

    assert [movie["id"] for movie in response.json()["movies"]] == sorted(movie.id for movie in catalog.values())


async def test_genre_details_without_movies(client, db_session, catalog):
    comedy = (await db_session.execute(select(Genre).where(Genre.name == "Comedy"))).scalar_one()

    response = await client.get(f"{GENRES_URL}/{comedy.id}")

    assert response.status_code == 200
    assert response.json()["movies"] == []


async def test_genre_details_unknown_id_returns_404(client):
    response = await client.get(f"{GENRES_URL}/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "No genre with id:9999 found."
