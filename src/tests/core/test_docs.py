import pytest

from src.core.config import settings
from src.main import app
from src.tests.utils import TEST_EMAIL, TEST_PASSWORD, create_user

DOCS_URL = f"{settings.API_VERSION_PREFIX}{settings.DOCS_URL}"
REDOC_URL = f"{settings.API_VERSION_PREFIX}{settings.REDOC_URL}"
OPENAPI_URL = f"{settings.API_VERSION_PREFIX}{settings.OPENAPI_URL}"
PROTECTED = [DOCS_URL, REDOC_URL, OPENAPI_URL]


@pytest.mark.parametrize("url", PROTECTED)
async def test_docs_without_credentials_ask_for_basic_auth(client, url):
    response = await client.get(url)

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


@pytest.mark.parametrize(
    ("username", "password"),
    [(TEST_EMAIL, "WrongPassword1!"), ("nobody@example.com", TEST_PASSWORD)],
    ids=["wrong-password", "unknown-user"],
)
@pytest.mark.parametrize("url", PROTECTED)
async def test_docs_with_wrong_credentials_return_401(client, active_user, url, username, password):
    response = await client.get(url, auth=(username, password))

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


@pytest.mark.parametrize("url", PROTECTED)
async def test_docs_for_inactive_user_return_403(client, db_session, url):
    await create_user(db_session, is_active=False)

    response = await client.get(url, auth=(TEST_EMAIL, TEST_PASSWORD))

    assert response.status_code == 403


async def test_swagger_ui_loads_the_protected_schema(client, active_user):
    response = await client.get(DOCS_URL, auth=(TEST_EMAIL.upper(), TEST_PASSWORD))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "swagger-ui" in response.text
    assert f"'{OPENAPI_URL}'" in response.text


async def test_redoc_loads_the_protected_schema(client, active_user):
    response = await client.get(REDOC_URL, auth=(TEST_EMAIL, TEST_PASSWORD))

    assert response.status_code == 200
    assert "redoc" in response.text.lower()
    assert OPENAPI_URL in response.text


async def test_openapi_schema_describes_the_api_but_not_the_docs_routes(client, active_user):
    response = await client.get(OPENAPI_URL, auth=(TEST_EMAIL, TEST_PASSWORD))

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert f"{settings.API_VERSION_PREFIX}/movies" in paths
    assert not any(path in paths for path in PROTECTED)


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
async def test_default_fastapi_docs_are_disabled(client, url):
    response = await client.get(url)

    assert response.status_code == 404


def test_app_level_docs_are_turned_off():
    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)
