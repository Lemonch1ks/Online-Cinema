"""POST / PATCH / DELETE for genres, stars and directors: the same rules for all three."""

from dataclasses import dataclass

import pytest
from sqlalchemy import func, select

from src.auth.models import UserGroupEnum
from src.movies.models import Director, Genre, Movie, Star
from src.tests.utils import DIRECTORS_URL, GENRES_URL, MOVIES_URL, STARS_URL, headers_for


@dataclass(frozen=True)
class Entity:
    url: str
    model: type[Genre] | type[Star] | type[Director]
    label: str
    movie_field: str
    used: str
    used_movies: tuple[str, ...]
    other: str


ENTITIES = [
    pytest.param(
        Entity(GENRES_URL, Genre, "genre", "genres", "Drama", ("Forrest Gump", "Cast Away"), "Action"),
        id="genres",
    ),
    pytest.param(
        Entity(STARS_URL, Star, "star", "stars", "Tom Hanks", ("Forrest Gump", "Cast Away"), "Keanu Reeves"),
        id="stars",
    ),
    pytest.param(
        Entity(
            DIRECTORS_URL,
            Director,
            "director",
            "directors",
            "Robert Zemeckis",
            ("Forrest Gump", "Cast Away"),
            "Lana Wachowski",
        ),
        id="directors",
    ),
]

pytestmark = pytest.mark.parametrize("entity", ENTITIES)


async def names(db_session, entity: Entity) -> list[str]:
    return list(await db_session.scalars(select(entity.model.name).order_by(entity.model.name)))


async def id_of(db_session, entity: Entity, name: str) -> int:
    return (await db_session.execute(select(entity.model.id).where(entity.model.name == name))).scalar_one()


async def movies_of(db_session, entity: Entity, record_id: int) -> list[str]:
    stmt = (
        select(Movie.name)
        .join(getattr(Movie, entity.movie_field))
        .where(entity.model.id == record_id)
        .order_by(Movie.name)
    )
    return list(await db_session.scalars(stmt))


async def create_unused(db_session, entity: Entity, name: str = "Nobody") -> int:
    record = entity.model(name=name)
    db_session.add(record)
    await db_session.commit()
    return record.id


# --- access control ---


async def test_anonymous_gets_401_and_nothing_changes(client, db_session, catalog, entity):
    record_id = await id_of(db_session, entity, entity.used)
    before = await names(db_session, entity)

    responses = [
        await client.post(entity.url, json={"name": "New"}),
        await client.patch(f"{entity.url}/{record_id}", json={"name": "Renamed"}),
        await client.delete(f"{entity.url}/{record_id}"),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert await names(db_session, entity) == before


async def test_regular_user_gets_403_and_nothing_changes(client, db_session, catalog, entity):
    headers = await headers_for(client, db_session, UserGroupEnum.USER, "user@example.com")
    record_id = await create_unused(db_session, entity)
    before = await names(db_session, entity)

    responses = [
        await client.post(entity.url, json={"name": "New"}, headers=headers),
        await client.patch(f"{entity.url}/{record_id}", json={"name": "Renamed"}, headers=headers),
        await client.delete(f"{entity.url}/{record_id}", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert await names(db_session, entity) == before


@pytest.mark.parametrize("group", [UserGroupEnum.MODERATOR, UserGroupEnum.ADMIN])
async def test_moderator_and_admin_can_create(client, db_session, entity, group):
    headers = await headers_for(client, db_session, group, "staff@example.com")

    response = await client.post(entity.url, json={"name": "New"}, headers=headers)

    assert response.status_code == 201, response.text
    assert await names(db_session, entity) == ["New"]


# --- POST ---


async def test_create_returns_record_and_saves_it(client, db_session, moderator_headers, entity):
    response = await client.post(entity.url, json={"name": "  Western  "}, headers=moderator_headers)

    assert response.status_code == 201, response.text
    assert response.json() == {"id": await id_of(db_session, entity, "Western"), "name": "Western"}
    assert await names(db_session, entity) == ["Western"]


async def test_create_duplicate_ignoring_case_returns_409(client, db_session, catalog, moderator_headers, entity):
    before = await names(db_session, entity)

    response = await client.post(entity.url, json={"name": entity.used.upper()}, headers=moderator_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": f"{entity.label.capitalize()} '{entity.used.upper()}' already exists."}
    assert await names(db_session, entity) == before


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 256}, {"name": "A", "extra": 1}])
async def test_create_rejects_invalid_body(client, db_session, moderator_headers, entity, body):
    response = await client.post(entity.url, json=body, headers=moderator_headers)

    assert response.status_code == 422
    assert await names(db_session, entity) == []


# --- PATCH ---


async def test_rename_changes_name_seen_by_movies(client, db_session, catalog, moderator_headers, entity):
    record_id = await id_of(db_session, entity, entity.used)

    response = await client.patch(f"{entity.url}/{record_id}", json={"name": "Renamed"}, headers=moderator_headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"id": record_id, "name": "Renamed"}
    assert entity.used not in await names(db_session, entity)
    assert await movies_of(db_session, entity, record_id) == sorted(entity.used_movies)
    movie = await client.get(f"{MOVIES_URL}/{catalog[entity.used_movies[0]].id}")
    assert "Renamed" in [item["name"] for item in movie.json()[entity.movie_field]]


async def test_rename_to_another_records_name_returns_409(client, db_session, catalog, moderator_headers, entity):
    record_id = await id_of(db_session, entity, entity.used)
    before = await names(db_session, entity)

    response = await client.patch(
        f"{entity.url}/{record_id}", json={"name": entity.other.lower()}, headers=moderator_headers
    )

    assert response.status_code == 409
    assert response.json() == {"detail": f"{entity.label.capitalize()} '{entity.other.lower()}' already exists."}
    assert await names(db_session, entity) == before


async def test_rename_can_change_case_of_own_name(client, db_session, catalog, moderator_headers, entity):
    record_id = await id_of(db_session, entity, entity.used)

    response = await client.patch(
        f"{entity.url}/{record_id}", json={"name": entity.used.upper()}, headers=moderator_headers
    )

    assert response.status_code == 200, response.text
    assert entity.used.upper() in await names(db_session, entity)


@pytest.mark.parametrize("body", [{}, {"name": None}, {"name": ""}, {"name": "A", "extra": 1}])
async def test_rename_rejects_invalid_body(client, db_session, catalog, moderator_headers, entity, body):
    record_id = await id_of(db_session, entity, entity.used)
    before = await names(db_session, entity)

    response = await client.patch(f"{entity.url}/{record_id}", json=body, headers=moderator_headers)

    assert response.status_code == 422
    assert await names(db_session, entity) == before


async def test_rename_unknown_returns_404(client, moderator_headers, entity):
    response = await client.patch(f"{entity.url}/999", json={"name": "Renamed"}, headers=moderator_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": f"No {entity.label} with id:999 found."}


# --- DELETE ---


async def test_delete_unused_record(client, db_session, catalog, moderator_headers, entity):
    record_id = await create_unused(db_session, entity)
    before = await names(db_session, entity)

    response = await client.delete(f"{entity.url}/{record_id}", headers=moderator_headers)

    assert response.status_code == 204
    assert response.content == b""
    assert await names(db_session, entity) == [name for name in before if name != "Nobody"]
    assert (await client.get(f"{entity.url}/{record_id}")).status_code == 404


async def test_delete_used_record_returns_409_and_keeps_links(client, db_session, catalog, moderator_headers, entity):
    record_id = await id_of(db_session, entity, entity.used)

    response = await client.delete(f"{entity.url}/{record_id}", headers=moderator_headers)

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"{entity.label.capitalize()} is used in {len(entity.used_movies)} movies and cannot be deleted."
    }
    assert entity.used in await names(db_session, entity)
    assert await movies_of(db_session, entity, record_id) == sorted(entity.used_movies)


async def test_delete_unknown_returns_404(client, moderator_headers, entity):
    response = await client.delete(f"{entity.url}/999", headers=moderator_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": f"No {entity.label} with id:999 found."}


async def test_deleted_name_can_be_created_again_through_a_movie(client, db_session, moderator_headers, entity):
    record_id = await create_unused(db_session, entity, "Comeback")
    await client.delete(f"{entity.url}/{record_id}", headers=moderator_headers)
    movie = {
        "name": "New Movie",
        "year": 2020,
        "time": 100,
        "imdb": 7.0,
        "votes": 10,
        "price": "5.00",
        "description": "Something.",
        "certification": "PG",
        entity.movie_field: ["comeback"],
    }

    response = await client.post(MOVIES_URL, json=movie, headers=moderator_headers)

    assert response.status_code == 201, response.text
    assert await names(db_session, entity) == ["comeback"]
    count = (await db_session.execute(select(func.count()).select_from(entity.model))).scalar_one()
    assert count == 1
