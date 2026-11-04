"""Fills the database with a demo catalog: movies with genres, stars, directors and certifications.

Run inside the app container (or locally with the virtualenv):
    docker compose exec app python -m src.movies.seed

Safe to run again: movies that are already there (same name, year and length) are skipped,
and genres, stars, directors and certifications with an existing name are reused.
"""

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.database import SessionLocal
from src.movies.models import Certification, Director, Genre, Movie, Star

DEMO_MOVIES: list[dict[str, Any]] = [
    {
        "name": "The Shawshank Redemption",
        "year": 1994,
        "time": 142,
        "imdb": 9.3,
        "votes": 3000000,
        "meta_score": 82,
        "gross": 28.34,
        "price": "6.99",
        "certification": "R",
        "description": "A banker sentenced to life in prison holds on to hope over two decades behind bars.",
        "genres": ["Drama"],
        "stars": ["Tim Robbins", "Morgan Freeman"],
        "directors": ["Frank Darabont"],
    },
    {
        "name": "The Godfather",
        "year": 1972,
        "time": 175,
        "imdb": 9.2,
        "votes": 2100000,
        "meta_score": 100,
        "gross": 134.97,
        "price": "7.99",
        "certification": "R",
        "description": "The ageing head of a crime family hands his empire to a reluctant son.",
        "genres": ["Crime", "Drama"],
        "stars": ["Marlon Brando", "Al Pacino"],
        "directors": ["Francis Ford Coppola"],
    },
    {
        "name": "The Dark Knight",
        "year": 2008,
        "time": 152,
        "imdb": 9.0,
        "votes": 2900000,
        "meta_score": 84,
        "gross": 534.86,
        "price": "8.99",
        "certification": "PG-13",
        "description": "Batman faces the Joker, a criminal who wants to watch Gotham fall into chaos.",
        "genres": ["Action", "Crime", "Drama"],
        "stars": ["Christian Bale", "Heath Ledger"],
        "directors": ["Christopher Nolan"],
    },
    {
        "name": "Pulp Fiction",
        "year": 1994,
        "time": 154,
        "imdb": 8.9,
        "votes": 2300000,
        "meta_score": 95,
        "gross": 107.93,
        "price": "6.49",
        "certification": "R",
        "description": "Hitmen, a boxer and a gangster's wife cross paths in a few days in Los Angeles.",
        "genres": ["Crime", "Drama"],
        "stars": ["John Travolta", "Uma Thurman", "Samuel L. Jackson"],
        "directors": ["Quentin Tarantino"],
    },
    {
        "name": "Forrest Gump",
        "year": 1994,
        "time": 142,
        "imdb": 8.8,
        "votes": 2300000,
        "meta_score": 82,
        "gross": 330.25,
        "price": "4.99",
        "certification": "PG-13",
        "description": "A kind man from Alabama finds himself in the middle of decades of American history.",
        "genres": ["Drama", "Romance"],
        "stars": ["Tom Hanks", "Robin Wright"],
        "directors": ["Robert Zemeckis"],
    },
    {
        "name": "Inception",
        "year": 2010,
        "time": 148,
        "imdb": 8.8,
        "votes": 2600000,
        "meta_score": 74,
        "gross": 292.58,
        "price": "7.49",
        "certification": "PG-13",
        "description": "A thief who steals secrets from dreams is hired to plant an idea instead.",
        "genres": ["Action", "Sci-Fi"],
        "stars": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
        "directors": ["Christopher Nolan"],
    },
    {
        "name": "The Matrix",
        "year": 1999,
        "time": 136,
        "imdb": 8.7,
        "votes": 2100000,
        "meta_score": 73,
        "gross": 171.48,
        "price": "5.99",
        "certification": "R",
        "description": "A hacker discovers that the world he lives in is a simulation and joins the resistance.",
        "genres": ["Action", "Sci-Fi"],
        "stars": ["Keanu Reeves", "Laurence Fishburne"],
        "directors": ["Lana Wachowski", "Lilly Wachowski"],
    },
    {
        "name": "Interstellar",
        "year": 2014,
        "time": 169,
        "imdb": 8.7,
        "votes": 2200000,
        "meta_score": 74,
        "gross": 188.02,
        "price": "8.49",
        "certification": "PG-13",
        "description": "Astronauts travel through a wormhole to find a new home for humanity.",
        "genres": ["Adventure", "Drama", "Sci-Fi"],
        "stars": ["Matthew McConaughey", "Anne Hathaway"],
        "directors": ["Christopher Nolan"],
    },
    {
        "name": "Spirited Away",
        "year": 2001,
        "time": 125,
        "imdb": 8.6,
        "votes": 900000,
        "meta_score": 96,
        "gross": 10.06,
        "price": "5.49",
        "certification": "PG",
        "description": "A girl trapped in a world of spirits works in a bathhouse to save her parents.",
        "genres": ["Animation", "Adventure", "Family"],
        "stars": ["Rumi Hiiragi", "Miyu Irino"],
        "directors": ["Hayao Miyazaki"],
    },
    {
        "name": "Cast Away",
        "year": 2000,
        "time": 143,
        "imdb": 7.8,
        "votes": 650000,
        "meta_score": 73,
        "gross": 233.63,
        "price": "3.99",
        "certification": "PG-13",
        "description": "A courier survives a plane crash and has to live alone on a desert island.",
        "genres": ["Adventure", "Drama"],
        "stars": ["Tom Hanks", "Helen Hunt"],
        "directors": ["Robert Zemeckis"],
    },
    {
        "name": "The Grand Budapest Hotel",
        "year": 2014,
        "time": 99,
        "imdb": 8.1,
        "votes": 900000,
        "meta_score": 88,
        "gross": 59.1,
        "price": "4.49",
        "certification": "R",
        "description": "A hotel concierge and his lobby boy are drawn into the theft of a priceless painting.",
        "genres": ["Comedy", "Adventure"],
        "stars": ["Ralph Fiennes", "Tony Revolori"],
        "directors": ["Wes Anderson"],
    },
    {
        "name": "Toy Story",
        "year": 1995,
        "time": 81,
        "imdb": 8.3,
        "votes": 1100000,
        "meta_score": 96,
        "gross": 191.8,
        "price": "2.99",
        "certification": "G",
        "description": "A toy cowboy feels replaced when a space ranger action figure arrives in the room.",
        "genres": ["Animation", "Comedy", "Family"],
        "stars": ["Tom Hanks", "Tim Allen"],
        "directors": ["John Lasseter"],
    },
]

NamedModel = type[Genre] | type[Star] | type[Director] | type[Certification]


class Names:
    """Rows of one model by name: loads the existing ones, creates the missing ones once."""

    def __init__(self, db: AsyncSession, model: NamedModel) -> None:
        self._db = db
        self._model = model
        self._rows: dict[str, Any] = {}

    async def load(self) -> "Names":
        rows: list[Any] = list(await self._db.scalars(select(self._model)))
        self._rows = {row.name: row for row in rows}
        return self

    def get(self, name: str) -> Any:
        if name not in self._rows:
            self._rows[name] = self._model(name=name)
        return self._rows[name]


async def seed_catalog(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Adds the demo movies that are not in the database yet; returns how many were added."""
    async with session_factory() as db:
        existing = {tuple(row) for row in await db.execute(select(Movie.name, Movie.year, Movie.time))}
        genres = await Names(db, Genre).load()
        stars = await Names(db, Star).load()
        directors = await Names(db, Director).load()
        certifications = await Names(db, Certification).load()

        added = 0
        for data in DEMO_MOVIES:
            if (data["name"], data["year"], data["time"]) in existing:
                continue
            db.add(
                Movie(
                    name=data["name"],
                    year=data["year"],
                    time=data["time"],
                    imdb=data["imdb"],
                    votes=data["votes"],
                    meta_score=data["meta_score"],
                    gross=data["gross"],
                    description=data["description"],
                    price=Decimal(data["price"]),
                    certification=certifications.get(data["certification"]),
                    genres=[genres.get(name) for name in data["genres"]],
                    stars=[stars.get(name) for name in data["stars"]],
                    directors=[directors.get(name) for name in data["directors"]],
                )
            )
            added += 1
        await db.commit()
    return added


def main() -> None:
    added = asyncio.run(seed_catalog(SessionLocal))
    print(f"Added {added} demo movies.")


if __name__ == "__main__":  # pragma: no cover
    main()
