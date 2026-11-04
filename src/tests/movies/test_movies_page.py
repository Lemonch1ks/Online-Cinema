"""get_movies_page works on top of any base query, not only the whole catalog (favorites will use it)."""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from starlette.requests import Request

from src.movies.filters import MoviesQuery
from src.movies.models import Movie
from src.movies.service import get_movies_page

PATH = "/api/v1/favorites"


def make_request(query_string: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("test", 80),
            "path": PATH,
            "root_path": "",
            "query_string": query_string.encode(),
            "headers": [],
        }
    )


def split_link(link: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(link)
    return parts.path, parse_qs(parts.query)


def page_names(page) -> list[str]:
    return [movie.name for movie in page.movies]


async def test_only_movies_from_base_query_are_returned_and_counted(db_session, catalog):
    base = select(Movie).where(Movie.year >= 1999)

    page = await get_movies_page(db_session, make_request(), base, MoviesQuery())

    assert page_names(page) == ["The Matrix", "Cast Away", "Inception"]
    assert (page.total_items, page.total_pages) == (3, 1)


async def test_search_filter_and_sort_apply_inside_base_query(db_session, catalog):
    base = select(Movie).where(Movie.name != "Inception")
    query = MoviesQuery(search_param="a", year_from=1995, sort_by="price", order_type="asc")

    page = await get_movies_page(db_session, make_request(), base, query)

    assert page_names(page) == ["The Matrix", "Cast Away"]
    assert page.total_items == 2


async def test_pagination_links_keep_the_request_path_and_params(db_session, catalog):
    base = select(Movie).where(Movie.year >= 1999)
    query = MoviesQuery(page=2, per_page=1, sort_by="year")

    page = await get_movies_page(db_session, make_request("page=2&per_page=1&sort_by=year"), base, query)

    assert page_names(page) == ["Cast Away"]
    assert (page.total_items, page.total_pages) == (3, 3)
    assert split_link(page.prev_page) == (PATH, {"page": ["1"], "per_page": ["1"], "sort_by": ["year"]})
    assert split_link(page.next_page) == (PATH, {"page": ["3"], "per_page": ["1"], "sort_by": ["year"]})


async def test_empty_base_query_gives_empty_page(db_session, catalog):
    page = await get_movies_page(db_session, make_request(), select(Movie).where(Movie.id < 0), MoviesQuery())

    assert page.movies == []
    assert (page.total_items, page.total_pages, page.prev_page, page.next_page) == (0, 0, None, None)
