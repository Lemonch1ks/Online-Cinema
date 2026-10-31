from decimal import Decimal

import pytest

from src.movies.models import Certification, Director, Genre, Movie, Star

# Small, hand-made catalog: every value is chosen so filters and sorting have one clear answer.
# id order: Matrix(1), Forrest Gump(2), Cast Away(3), Inception(4)
MOVIES = [
    {
        "name": "The Matrix", "year": 1999, "imdb": 8.7, "meta_score": 73, "gross": 171.5,
        "description": "A hacker learns the truth about reality.",
        "genres": ["Action"], "stars": ["Keanu Reeves"], "directors": ["Lana Wachowski"],
    },
    {
        "name": "Forrest Gump", "year": 1994, "imdb": 8.8, "meta_score": 82, "gross": 330.2,
        "description": "Life is like a box of chocolates.",
        "genres": ["Drama"], "stars": ["Tom Hanks"], "directors": ["Robert Zemeckis"],
    },
    {
        "name": "Cast Away", "year": 2000, "imdb": 7.8, "meta_score": 74, "gross": 233.6,
        "description": "A man is stranded on an ISLAND.",
        "genres": ["Drama"], "stars": ["Tom Hanks"], "directors": ["Robert Zemeckis"],
    },
    {
        "name": "Inception", "year": 2010, "imdb": 8.6, "meta_score": 84, "gross": 292.6,
        "description": "Dreams within dreams, 100% mind-bending.",
        "genres": ["Action"], "stars": ["Leonardo DiCaprio"], "directors": ["Christopher Nolan"],
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
            price=Decimal("9.99"),
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
