import logging
import re
import struct
import zlib
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import UserProfile
from src.core.config import settings
from src.tests.utils import PROFILE_URL, make_image

PROFILE_DATA = {
    "first_name": "Anna",
    "last_name": "O'Neil",
    "gender": "WOMAN",
    "date_of_birth": "1995-04-12",
    "info": "Loves sci-fi.",
}


def png_header_only(width: int, height: int) -> bytes:
    """A tiny PNG that only declares its size: unpacking it would need width * height * 3 bytes of memory."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def avatar_file(data: bytes | None = None, filename: str = "avatar.png", content_type: str = "image/png") -> dict:
    return {"avatar": (filename, data if data is not None else make_image("PNG"), content_type)}


async def create_profile(client, headers, data=None, files=None):
    return await client.post(PROFILE_URL, data=PROFILE_DATA if data is None else data, files=files, headers=headers)


async def get_db_profile(db_session, user_id: int) -> UserProfile | None:
    stmt = select(UserProfile).where(UserProfile.user_id == user_id).execution_options(populate_existing=True)
    return (await db_session.execute(stmt)).scalar_one_or_none()


@pytest.fixture()
def broken_commit(monkeypatch):
    """Call it after the test data is prepared: from then on every commit fails."""

    def apply() -> None:
        async def failing_commit(self) -> None:
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

        monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    return apply


# --- POST /profiles/me ---

async def test_create_profile_without_avatar(client, db_session, active_user, auth_headers, storage):
    response = await create_profile(client, auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body == {"id": body["id"], "user_id": active_user.id, **PROFILE_DATA, "avatar_url": None}
    profile = await get_db_profile(db_session, active_user.id)
    assert profile.first_name == "Anna"
    assert profile.avatar is None
    assert storage.files == {}


@pytest.mark.parametrize(("image_format", "extension", "content_type"), [("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg")])
async def test_create_profile_with_avatar(
    client, db_session, active_user, auth_headers, storage, image_format, extension, content_type
):
    image = make_image(image_format)

    response = await create_profile(client, auth_headers, files=avatar_file(image, f"me.{extension}", content_type))

    assert response.status_code == 201
    [(key, (data, stored_type))] = storage.files.items()
    assert re.fullmatch(rf"{active_user.id}/[0-9a-f]{{32}}\.{extension}", key)
    assert data == image
    assert stored_type == content_type
    assert response.json()["avatar_url"] == storage.url(key)
    assert (await get_db_profile(db_session, active_user.id)).avatar == key


async def test_create_profile_with_only_some_fields(client, auth_headers):
    response = await create_profile(client, auth_headers, data={"first_name": "Bob"})

    assert response.status_code == 201
    assert response.json()["first_name"] == "Bob"
    assert response.json()["last_name"] is None


async def test_create_profile_twice_returns_409(client, auth_headers, storage):
    await create_profile(client, auth_headers)

    response = await create_profile(client, auth_headers, files=avatar_file())

    assert response.status_code == 409
    assert storage.files == {}


@pytest.mark.parametrize(
    "data",
    [
        {"first_name": "Anna1"},
        {"last_name": "Smith_Jones"},
        {"first_name": "x" * 51},
        {"gender": "OTHER"},
        {"date_of_birth": "1899-12-31"},
        {"date_of_birth": (date.today() + timedelta(days=1)).isoformat()},
        {"date_of_birth": "not-a-date"},
        {"info": "x" * 1001},
    ],
)
async def test_create_profile_with_invalid_fields_returns_422(client, db_session, active_user, auth_headers, storage, data):
    response = await create_profile(client, auth_headers, data={**PROFILE_DATA, **data}, files=avatar_file())

    assert response.status_code == 422
    assert storage.files == {}
    assert await get_db_profile(db_session, active_user.id) is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"just some text, not an image", "not a valid image"),
        (make_image("PNG")[:40], "not a valid image"),
        (make_image("GIF"), "Unsupported avatar format GIF"),
    ],
    ids=["text-named-png", "truncated-png", "gif"],
)
async def test_create_profile_with_invalid_avatar_returns_422(client, db_session, active_user, auth_headers, storage, data, message):
    response = await create_profile(client, auth_headers, files=avatar_file(data, "avatar.png", "image/png"))

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert storage.files == {}
    assert await get_db_profile(db_session, active_user.id) is None


@pytest.mark.parametrize(
    ("width", "height"),
    [(20_000, 20_000), (10_000, 10_000)],
    ids=["above-pillow-error-limit", "above-pillow-warning-limit"],
)
async def test_create_profile_with_decompression_bomb_returns_422(
    client, db_session, active_user, auth_headers, storage, width, height
):
    bomb = png_header_only(width, height)
    assert len(bomb) < 100

    response = await create_profile(client, auth_headers, files=avatar_file(bomb))

    assert response.status_code == 422
    assert storage.files == {}
    assert await get_db_profile(db_session, active_user.id) is None


async def test_create_profile_with_too_big_avatar_returns_422(client, auth_headers, storage, monkeypatch):
    monkeypatch.setattr(settings, "AVATAR_MAX_SIZE", 50)

    response = await create_profile(client, auth_headers, files=avatar_file(make_image("PNG", size=(64, 64))))

    assert response.status_code == 422
    assert "must not be larger" in response.json()["detail"]
    assert storage.files == {}


async def test_create_profile_when_storage_is_down_returns_500(client, db_session, active_user, auth_headers, storage, caplog):
    storage.fail_upload = True

    with caplog.at_level(logging.ERROR):
        response = await create_profile(client, auth_headers, files=avatar_file())

    assert response.status_code == 500
    assert await get_db_profile(db_session, active_user.id) is None
    assert "Failed to upload avatar" in caplog.text


async def test_create_profile_db_error_removes_uploaded_avatar(client, auth_headers, storage, broken_commit):
    broken_commit()

    response = await create_profile(client, auth_headers, files=avatar_file())

    assert response.status_code == 500
    assert storage.files == {}


async def test_create_profile_db_error_without_avatar(client, auth_headers, storage, broken_commit):
    broken_commit()

    response = await create_profile(client, auth_headers)

    assert response.status_code == 500


# --- GET /profiles/me ---

async def test_read_profile(client, auth_headers, storage):
    created = (await create_profile(client, auth_headers, files=avatar_file())).json()

    response = await client.get(PROFILE_URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == created


async def test_read_profile_when_none_returns_404(client, auth_headers):
    response = await client.get(PROFILE_URL, headers=auth_headers)

    assert response.status_code == 404


# --- PATCH /profiles/me ---

async def test_update_profile_changes_only_sent_fields(client, auth_headers):
    await create_profile(client, auth_headers)

    response = await client.patch(PROFILE_URL, data={"info": "Now into documentaries.", "gender": "MAN"}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["info"] == "Now into documentaries."
    assert body["gender"] == "MAN"
    assert body["first_name"] == PROFILE_DATA["first_name"]
    assert body["date_of_birth"] == PROFILE_DATA["date_of_birth"]


async def test_update_profile_replaces_avatar_and_deletes_old_file(client, db_session, active_user, auth_headers, storage):
    old_url = (await create_profile(client, auth_headers, files=avatar_file())).json()["avatar_url"]
    [old_key] = storage.files

    response = await client.patch(PROFILE_URL, files=avatar_file(make_image("JPEG"), "new.jpg", "image/jpeg"), headers=auth_headers)

    assert response.status_code == 200
    [new_key] = storage.files
    assert new_key != old_key
    assert new_key.endswith(".jpg")
    assert response.json()["avatar_url"] == storage.url(new_key) != old_url
    assert (await get_db_profile(db_session, active_user.id)).avatar == new_key


async def test_update_profile_first_avatar(client, auth_headers, storage):
    await create_profile(client, auth_headers)

    response = await client.patch(PROFILE_URL, files=avatar_file(), headers=auth_headers)

    assert response.status_code == 200
    assert len(storage.files) == 1


async def test_update_profile_without_avatar_keeps_it(client, auth_headers, storage):
    url = (await create_profile(client, auth_headers, files=avatar_file())).json()["avatar_url"]

    response = await client.patch(PROFILE_URL, data={"first_name": "Bob"}, headers=auth_headers)

    assert response.json()["avatar_url"] == url
    assert len(storage.files) == 1


async def test_update_profile_when_none_returns_404(client, auth_headers):
    response = await client.patch(PROFILE_URL, data={"first_name": "Bob"}, headers=auth_headers)

    assert response.status_code == 404


async def test_update_profile_with_invalid_field_returns_422(client, db_session, active_user, auth_headers):
    await create_profile(client, auth_headers)

    response = await client.patch(PROFILE_URL, data={"first_name": "B0b"}, headers=auth_headers)

    assert response.status_code == 422
    assert (await get_db_profile(db_session, active_user.id)).first_name == PROFILE_DATA["first_name"]


async def test_update_profile_db_error_keeps_old_avatar(client, db_session, active_user, auth_headers, storage, broken_commit):
    await create_profile(client, auth_headers, files=avatar_file())
    [old_key] = storage.files
    broken_commit()

    response = await client.patch(PROFILE_URL, files=avatar_file(), headers=auth_headers)

    assert response.status_code == 500
    assert list(storage.files) == [old_key]
    assert (await get_db_profile(db_session, active_user.id)).avatar == old_key


async def test_update_profile_db_error_without_avatar(client, auth_headers, broken_commit):
    await create_profile(client, auth_headers)
    broken_commit()

    response = await client.patch(PROFILE_URL, data={"first_name": "Bob"}, headers=auth_headers)

    assert response.status_code == 500


async def test_update_profile_succeeds_if_old_avatar_cannot_be_deleted(client, auth_headers, storage, caplog):
    await create_profile(client, auth_headers, files=avatar_file())
    [old_key] = storage.files
    storage.fail_delete = True

    with caplog.at_level(logging.ERROR):
        response = await client.patch(PROFILE_URL, files=avatar_file(), headers=auth_headers)

    assert response.status_code == 200
    assert old_key in storage.files
    assert f"Failed to delete avatar {old_key}" in caplog.text


# --- auth ---

@pytest.mark.parametrize("method", ["get", "post", "patch"])
async def test_profile_endpoints_require_auth(client, method):
    response = await client.request(method.upper(), PROFILE_URL)

    assert response.status_code == 401
