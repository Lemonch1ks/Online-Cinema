from dataclasses import dataclass
from decimal import Decimal

import pytest

from src.auth.models import UserGroupEnum
from src.movies.models import Certification, Director, Genre, Movie, Star
from src.tests.utils import bearer, create_user_in_group, headers_for, login

MOVIES = [
    {
        "name": "The Matrix",
        "price": "9.99",
        "year": 1999,
        "imdb": 8.7,
        "meta_score": 73,
        "gross": 171.5,
        "description": "A hacker learns the truth about reality.",
        "genres": ["Action"],
        "stars": ["Keanu Reeves"],
        "directors": ["Lana Wachowski"],
    },
    {
        "name": "Forrest Gump",
        "price": "4.99",
        "year": 1994,
        "imdb": 8.8,
        "meta_score": 82,
        "gross": 330.2,
        "description": "Life is like a box of chocolates.",
        "genres": ["Drama"],
        "stars": ["Tom Hanks"],
        "directors": ["Robert Zemeckis"],
    },
    {
        "name": "Cast Away",
        "price": "14.99",
        "year": 2000,
        "imdb": 7.8,
        "meta_score": 74,
        "gross": 233.6,
        "description": "A man is stranded on an ISLAND.",
        "genres": ["Drama"],
        "stars": ["Tom Hanks"],
        "directors": ["Robert Zemeckis"],
    },
    {
        "name": "Inception",
        "price": "7.49",
        "year": 2010,
        "imdb": 8.6,
        "meta_score": 84,
        "gross": 292.6,
        "description": "Dreams within dreams, 100% mind-bending.",
        "genres": ["Action"],
        "stars": ["Leonardo DiCaprio"],
        "directors": ["Christopher Nolan"],
    },
]
GENRES_WITHOUT_MOVIES = ["Comedy"]


@pytest.fixture()
async def catalog(db_session) -> dict[str, Movie]:
    certification = Certification(name="PG-13")
    genres = {name: Genre(name=name) for name in ["Action", "Drama", *GENRES_WITHOUT_MOVIES]}
    stars: dict[str, Star] = {}
    directors: dict[str, Director] = {}

    movies = {}
    for data in MOVIES:
        movie = Movie(
            name=data["name"],
            year=data["year"],
            time=120,
            imdb=data["imdb"],
            votes=1000,
            meta_score=data["meta_score"],
            gross=data["gross"],
            description=data["description"],
            price=Decimal(data["price"]),
            certification=certification,
            genres=[genres[name] for name in data["genres"]],
            stars=[stars.setdefault(name, Star(name=name)) for name in data["stars"]],
            directors=[directors.setdefault(name, Director(name=name)) for name in data["directors"]],
        )
        movies[movie.name] = movie
        db_session.add(movie)

    db_session.add_all(genres.values())
    await db_session.commit()
    return movies


@pytest.fixture()
async def moderator_headers(client, db_session) -> dict:
    return await headers_for(client, db_session, UserGroupEnum.MODERATOR, "moderator@example.com")


@dataclass(frozen=True)
class Member:
    """A logged-in user: id for checks in the database, headers for requests."""

    id: int
    email: str
    headers: dict


async def make_member(client, db_session, email: str, group: UserGroupEnum = UserGroupEnum.USER) -> Member:
    user = await create_user_in_group(db_session, email, group)
    return Member(user.id, email, bearer((await login(client, email))["access_token"]))


@pytest.fixture()
async def alice(client, db_session) -> Member:
    return await make_member(client, db_session, "alice@example.com")


@pytest.fixture()
async def bob(client, db_session) -> Member:
    return await make_member(client, db_session, "bob@example.com")
