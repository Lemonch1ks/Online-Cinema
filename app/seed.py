"""Наполнение базы тестовыми данными (каталог фильмов).

Запуск (после `alembic upgrade head`):
    poetry run python -m app.seed

Скрипт можно запускать повторно: уже существующие записи он не дублирует.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Certification, Director, Genre, Movie, Star

# Данные близки к реальным (IMDb), цены придуманы.
MOVIES = [
    {
        "name": "The Shawshank Redemption", "year": 1994, "time": 142, "imdb": 9.3,
        "votes": 2_950_000, "meta_score": 82, "gross": 28_341_469, "price": "4.99",
        "certification": "R", "genres": ["Drama"],
        "directors": ["Frank Darabont"], "stars": ["Tim Robbins", "Morgan Freeman"],
        "description": "Two imprisoned men bond over a number of years, finding solace "
        "and eventual redemption through acts of common decency.",
    },
    {
        "name": "The Godfather", "year": 1972, "time": 175, "imdb": 9.2,
        "votes": 2_050_000, "meta_score": 100, "gross": 134_966_411, "price": "5.99",
        "certification": "R", "genres": ["Crime", "Drama"],
        "directors": ["Francis Ford Coppola"], "stars": ["Marlon Brando", "Al Pacino"],
        "description": "The aging patriarch of an organized crime dynasty transfers "
        "control of his clandestine empire to his reluctant son.",
    },
    {
        "name": "The Dark Knight", "year": 2008, "time": 152, "imdb": 9.0,
        "votes": 2_930_000, "meta_score": 84, "gross": 534_858_444, "price": "6.99",
        "certification": "PG-13", "genres": ["Action", "Crime", "Drama"],
        "directors": ["Christopher Nolan"], "stars": ["Christian Bale", "Heath Ledger"],
        "description": "Batman faces the Joker, a criminal mastermind who wants to "
        "plunge Gotham City into anarchy.",
    },
    {
        "name": "Pulp Fiction", "year": 1994, "time": 154, "imdb": 8.9,
        "votes": 2_260_000, "meta_score": 95, "gross": 107_928_762, "price": "4.99",
        "certification": "R", "genres": ["Crime", "Drama"],
        "directors": ["Quentin Tarantino"],
        "stars": ["John Travolta", "Uma Thurman", "Samuel L. Jackson"],
        "description": "The lives of two mob hitmen, a boxer, a gangster and his wife "
        "intertwine in four tales of violence and redemption.",
    },
    {
        "name": "Inception", "year": 2010, "time": 148, "imdb": 8.8,
        "votes": 2_600_000, "meta_score": 74, "gross": 292_576_195, "price": "6.99",
        "certification": "PG-13", "genres": ["Action", "Adventure", "Sci-Fi"],
        "directors": ["Christopher Nolan"],
        "stars": ["Leonardo DiCaprio", "Joseph Gordon-Levitt", "Elliot Page"],
        "description": "A thief who steals corporate secrets through dream-sharing "
        "technology is given the task of planting an idea into a CEO's mind.",
    },
    {
        "name": "Fight Club", "year": 1999, "time": 139, "imdb": 8.8,
        "votes": 2_380_000, "meta_score": 67, "gross": 37_030_102, "price": "4.49",
        "certification": "R", "genres": ["Drama"],
        "directors": ["David Fincher"], "stars": ["Brad Pitt", "Edward Norton"],
        "description": "An insomniac office worker and a devil-may-care soap maker "
        "form an underground fight club that evolves into much more.",
    },
    {
        "name": "Forrest Gump", "year": 1994, "time": 142, "imdb": 8.8,
        "votes": 2_300_000, "meta_score": 82, "gross": 330_252_182, "price": "4.99",
        "certification": "PG-13", "genres": ["Drama", "Romance"],
        "directors": ["Robert Zemeckis"], "stars": ["Tom Hanks", "Robin Wright"],
        "description": "The history of the United States from the 1950s to the '70s "
        "unfolds from the perspective of an Alabama man with an IQ of 75.",
    },
    {
        "name": "The Matrix", "year": 1999, "time": 136, "imdb": 8.7,
        "votes": 2_100_000, "meta_score": 73, "gross": 171_479_930, "price": "5.49",
        "certification": "R", "genres": ["Action", "Sci-Fi"],
        "directors": ["Lana Wachowski", "Lilly Wachowski"],
        "stars": ["Keanu Reeves", "Laurence Fishburne", "Carrie-Anne Moss"],
        "description": "A computer hacker learns that the world he lives in is a "
        "simulation and joins a rebellion against its controllers.",
    },
    {
        "name": "Interstellar", "year": 2014, "time": 169, "imdb": 8.7,
        "votes": 2_250_000, "meta_score": 74, "gross": 188_020_017, "price": "7.99",
        "certification": "PG-13", "genres": ["Adventure", "Drama", "Sci-Fi"],
        "directors": ["Christopher Nolan"],
        "stars": ["Matthew McConaughey", "Anne Hathaway", "Jessica Chastain"],
        "description": "A team of explorers travel through a wormhole in space in an "
        "attempt to ensure humanity's survival.",
    },
    {
        "name": "Spirited Away", "year": 2001, "time": 125, "imdb": 8.6,
        "votes": 900_000, "meta_score": 96, "gross": 10_055_859, "price": "5.99",
        "certification": "PG", "genres": ["Animation", "Adventure", "Family"],
        "directors": ["Hayao Miyazaki"], "stars": ["Rumi Hiiragi", "Miyu Irino"],
        "description": "A ten-year-old girl wanders into a world ruled by gods, "
        "witches and spirits, where humans are changed into beasts.",
    },
    {
        "name": "Parasite", "year": 2019, "time": 132, "imdb": 8.5,
        "votes": 1_000_000, "meta_score": 96, "gross": 53_369_749, "price": "7.49",
        "certification": "R", "genres": ["Comedy", "Drama", "Thriller"],
        "directors": ["Bong Joon Ho"], "stars": ["Song Kang-ho", "Cho Yeo-jeong"],
        "description": "Greed and class discrimination threaten the newly formed "
        "symbiotic relationship between the wealthy Park family and the poor Kim clan.",
    },
    {
        "name": "The Lion King", "year": 1994, "time": 88, "imdb": 8.5,
        "votes": 1_150_000, "meta_score": 88, "gross": 422_783_777, "price": "3.99",
        "certification": "G", "genres": ["Animation", "Adventure", "Family"],
        "directors": ["Roger Allers", "Rob Minkoff"],
        "stars": ["Matthew Broderick", "Jeremy Irons"],
        "description": "Lion prince Simba flees his kingdom after the murder of his "
        "father, only to learn the true meaning of responsibility.",
    },
    {
        "name": "Gladiator", "year": 2000, "time": 155, "imdb": 8.5,
        "votes": 1_700_000, "meta_score": 67, "gross": 187_705_427, "price": "4.99",
        "certification": "R", "genres": ["Action", "Adventure", "Drama"],
        "directors": ["Ridley Scott"], "stars": ["Russell Crowe", "Joaquin Phoenix"],
        "description": "A former Roman general sets out to exact vengeance against "
        "the corrupt emperor who murdered his family and sent him into slavery.",
    },
    {
        "name": "Whiplash", "year": 2014, "time": 106, "imdb": 8.5,
        "votes": 1_000_000, "meta_score": 89, "gross": 13_092_000, "price": "5.49",
        "certification": "R", "genres": ["Drama", "Music"],
        "directors": ["Damien Chazelle"], "stars": ["Miles Teller", "J.K. Simmons"],
        "description": "A promising young drummer enrolls at a cut-throat music "
        "conservatory where his dreams are mentored by an abusive instructor.",
    },
    {
        "name": "Back to the Future", "year": 1985, "time": 116, "imdb": 8.5,
        "votes": 1_350_000, "meta_score": 87, "gross": 210_609_762, "price": "3.99",
        "certification": "PG", "genres": ["Adventure", "Comedy", "Sci-Fi"],
        "directors": ["Robert Zemeckis"],
        "stars": ["Michael J. Fox", "Christopher Lloyd"],
        "description": "Teenager Marty McFly is accidentally sent thirty years into "
        "the past in a time-traveling DeLorean invented by his friend Doc Brown.",
    },
    {
        "name": "Alien", "year": 1979, "time": 117, "imdb": 8.5,
        "votes": 980_000, "meta_score": 89, "gross": 78_900_000, "price": "3.99",
        "certification": "R", "genres": ["Horror", "Sci-Fi"],
        "directors": ["Ridley Scott"], "stars": ["Sigourney Weaver", "Tom Skerritt"],
        "description": "The crew of a commercial spacecraft encounters a deadly "
        "lifeform after investigating an unknown transmission.",
    },
    {
        "name": "Toy Story", "year": 1995, "time": 81, "imdb": 8.3,
        "votes": 1_100_000, "meta_score": 96, "gross": 191_796_233, "price": "3.49",
        "certification": "G", "genres": ["Animation", "Comedy", "Family"],
        "directors": ["John Lasseter"], "stars": ["Tom Hanks", "Tim Allen"],
        "description": "A cowboy doll is profoundly threatened and jealous when a new "
        "spaceman action figure supplants him as top toy in a boy's bedroom.",
    },
    {
        "name": "La La Land", "year": 2016, "time": 128, "imdb": 8.0,
        "votes": 680_000, "meta_score": 94, "gross": 151_101_803, "price": "5.99",
        "certification": "PG-13", "genres": ["Comedy", "Drama", "Music", "Romance"],
        "directors": ["Damien Chazelle"], "stars": ["Ryan Gosling", "Emma Stone"],
        "description": "While navigating their careers in Los Angeles, a pianist and "
        "an actress fall in love while attempting to reconcile their aspirations.",
    },
    {
        "name": "Get Out", "year": 2017, "time": 104, "imdb": 7.8,
        "votes": 720_000, "meta_score": 85, "gross": 176_040_665, "price": "5.49",
        "certification": "R", "genres": ["Horror", "Mystery", "Thriller"],
        "directors": ["Jordan Peele"], "stars": ["Daniel Kaluuya", "Allison Williams"],
        "description": "A young African-American visits his white girlfriend's parents "
        "for the weekend, where his uneasiness eventually reaches a boiling point.",
    },
    {
        "name": "Dune: Part Two", "year": 2024, "time": 166, "imdb": 8.5,
        "votes": 650_000, "meta_score": 79, "gross": 282_144_358, "price": "9.99",
        "certification": "PG-13", "genres": ["Action", "Adventure", "Drama", "Sci-Fi"],
        "directors": ["Denis Villeneuve"],
        "stars": ["Timothée Chalamet", "Zendaya", "Rebecca Ferguson"],
        "description": "Paul Atreides unites with the Fremen while on a path of "
        "revenge against the conspirators who destroyed his family.",
    },
]

# Жанр без фильмов — чтобы в /genres было видно movies_count = 0
EXTRA_GENRES = ["Documentary", "Western"]


def get_or_create(db: Session, model, name: str):
    """Находит запись по имени или создаёт новую (имена уникальны)."""
    obj = db.scalar(select(model).where(model.name == name))
    if obj is None:
        obj = model(name=name)
        db.add(obj)
    return obj


def seed(db: Session) -> int:
    for name in EXTRA_GENRES:
        get_or_create(db, Genre, name)

    created = 0
    for data in MOVIES:
        exists = db.scalar(
            select(Movie).where(
                Movie.name == data["name"], Movie.year == data["year"], Movie.time == data["time"]
            )
        )
        if exists:
            continue

        movie = Movie(
            name=data["name"],
            year=data["year"],
            time=data["time"],
            imdb=data["imdb"],
            votes=data["votes"],
            meta_score=data["meta_score"],
            gross=data["gross"],
            description=data["description"],
            price=Decimal(data["price"]),
            certification=get_or_create(db, Certification, data["certification"]),
            genres=[get_or_create(db, Genre, g) for g in data["genres"]],
            directors=[get_or_create(db, Director, d) for d in data["directors"]],
            stars=[get_or_create(db, Star, s) for s in data["stars"]],
        )
        db.add(movie)
        # flush отправляет INSERT в БД (без commit), чтобы следующий
        # get_or_create нашёл только что созданных актёров/жанры
        db.flush()
        created += 1

    db.commit()
    return created


if __name__ == "__main__":
    with SessionLocal() as session:
        count = seed(session)
    print(f"Добавлено фильмов: {count} (всего в наборе: {len(MOVIES)})")
