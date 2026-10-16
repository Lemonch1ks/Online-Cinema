# Импортируем все модели здесь, чтобы Alembic "видел" их через Base.metadata
from app.models.movies import (
    Certification,
    Director,
    Genre,
    Movie,
    Star,
    movie_directors,
    movie_genres,
    movie_stars,
)

__all__ = [
    "Certification",
    "Director",
    "Genre",
    "Movie",
    "Star",
    "movie_directors",
    "movie_genres",
    "movie_stars",
]
