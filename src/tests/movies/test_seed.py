"""The demo catalog script: fills an empty database and can be run again without duplicates."""

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.movies import seed
from src.movies.models import Certification, Director, Genre, Movie, Star
from src.tests.utils import GENRES_URL, MOVIES_URL


async def count(db_session, model) -> int:
    return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seed_fills_an_empty_catalog(client, db_session, session_factory):
    added = await seed.seed_catalog(session_factory)

    assert added == len(seed.DEMO_MOVIES) >= 10
    movies = list(
        await db_session.scalars(
            select(Movie).options(
                selectinload(Movie.genres),
                selectinload(Movie.stars),
                selectinload(Movie.directors),
                selectinload(Movie.certification),
            )
        )
    )
    assert sorted(movie.name for movie in movies) == sorted(data["name"] for data in seed.DEMO_MOVIES)
    for movie in movies:
        assert movie.genres and movie.stars and movie.directors and movie.certification
        assert movie.price > 0
    # Shared names are one row each: a star of several movies is not repeated.
    expected_stars = {name for data in seed.DEMO_MOVIES for name in data["stars"]}
    assert await count(db_session, Star) == len(expected_stars)

    # The catalog API shows them right away.
    response = await client.get(MOVIES_URL, params={"per_page": 20})
    assert response.json()["total_items"] == len(seed.DEMO_MOVIES)
    genres = await client.get(GENRES_URL)
    assert genres.status_code == 200
    counts = {genre["name"]: genre["movies_count"] for genre in genres.json()["genres"]}
    expected = {}
    for data in seed.DEMO_MOVIES:
        for name in data["genres"]:
            expected[name] = expected.get(name, 0) + 1
    assert counts == expected


async def test_seed_again_adds_nothing(db_session, session_factory):
    await seed.seed_catalog(session_factory)
    sizes = [await count(db_session, model) for model in (Movie, Genre, Star, Director, Certification)]

    added = await seed.seed_catalog(session_factory)

    assert added == 0
    assert [await count(db_session, model) for model in (Movie, Genre, Star, Director, Certification)] == sizes


async def test_seed_reuses_names_that_already_exist_and_keeps_other_movies(db_session, session_factory):
    first = seed.DEMO_MOVIES[0]
    db_session.add(Genre(name=first["genres"][0]))
    db_session.add(Certification(name=first["certification"]))
    db_session.add(
        Movie(
            name="A Moderator's Own Movie",
            year=2020,
            time=90,
            imdb=6.0,
            votes=10,
            description="Added through the API before the seed.",
            price=1,
            certification=Certification(name="Own rating"),
        )
    )
    await db_session.commit()

    added = await seed.seed_catalog(session_factory)

    assert added == len(seed.DEMO_MOVIES)
    assert await count(db_session, Movie) == len(seed.DEMO_MOVIES) + 1
    genres = list(await db_session.scalars(select(Genre.name).where(Genre.name == first["genres"][0])))
    assert genres == [first["genres"][0]]


def test_main_seeds_the_app_database(monkeypatch, capsys):
    calls = []

    async def fake_seed(session_factory):
        calls.append(session_factory)
        return 3

    monkeypatch.setattr(seed, "seed_catalog", fake_seed)

    seed.main()

    assert calls == [seed.SessionLocal]
    assert capsys.readouterr().out == "Added 3 demo movies.\n"
