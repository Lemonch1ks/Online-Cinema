"""Unit tests for S3Storage with a fake S3 client (like FakeSMTP for emails): no MinIO needed."""
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from src.core.config import settings
from src.storage.dependencies import get_storage
from src.storage.s3 import S3Storage, StorageError


class FakeS3Client:
    """Mimics the aioboto3 S3 client: an async context manager with put_object / delete_object."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "FakeS3Client":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def _call(self, name: str, **kwargs) -> dict:
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error
        return {}

    async def put_object(self, **kwargs) -> dict:
        return await self._call("put_object", **kwargs)

    async def delete_object(self, **kwargs) -> dict:
        return await self._call("delete_object", **kwargs)


def make_storage(monkeypatch, error: Exception | None = None, public_url: str = "http://localhost:9000"):
    storage = S3Storage("http://minio:9000", public_url, "key", "secret", "avatars")
    client = FakeS3Client(error)
    created_with: list[dict] = []

    def fake_client(service_name, **kwargs):
        created_with.append({"service": service_name, **kwargs})
        return client

    monkeypatch.setattr(storage._session, "client", fake_client)
    return storage, client, created_with


async def test_upload_puts_object_into_bucket(monkeypatch):
    storage, client, created_with = make_storage(monkeypatch)

    await storage.upload("1/abc.png", b"data", content_type="image/png")

    assert client.calls == [("put_object", {"Bucket": "avatars", "Key": "1/abc.png", "Body": b"data", "ContentType": "image/png"})]
    assert created_with == [{"service": "s3", "endpoint_url": "http://minio:9000", "region_name": "us-east-1"}]


async def test_delete_removes_object(monkeypatch):
    storage, client, _ = make_storage(monkeypatch)

    await storage.delete("1/abc.png")

    assert client.calls == [("delete_object", {"Bucket": "avatars", "Key": "1/abc.png"})]


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "InvalidAccessKeyId", "Message": "bad key"}}, "PutObject"),
        EndpointConnectionError(endpoint_url="http://minio:9000"),
    ],
    ids=["client-error", "connection-error"],
)
@pytest.mark.parametrize("operation", ["upload", "delete"])
async def test_s3_errors_are_wrapped_in_storage_error(monkeypatch, error, operation):
    storage, _, _ = make_storage(monkeypatch, error=error)
    call = storage.upload("k", b"x", "text/plain") if operation == "upload" else storage.delete("k")

    with pytest.raises(StorageError) as raised:
        await call

    assert raised.value.__cause__ is error


@pytest.mark.parametrize("public_url", ["http://localhost:9000", "http://localhost:9000/"])
def test_url_uses_public_address(monkeypatch, public_url):
    storage, _, _ = make_storage(monkeypatch, public_url=public_url)

    assert storage.url("1/abc.png") == "http://localhost:9000/avatars/1/abc.png"


def test_get_storage_is_built_from_settings_and_cached():
    storage = get_storage()

    assert isinstance(storage, S3Storage)
    assert storage.url("k") == f"{settings.S3_PUBLIC_URL.rstrip('/')}/{settings.S3_BUCKET}/k"
    assert get_storage() is storage
