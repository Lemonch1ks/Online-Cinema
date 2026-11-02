import aioboto3
from botocore.exceptions import BotoCoreError, ClientError


class StorageError(Exception):
    """Base class for all exceptions raised by the storage module (routers do not need to know botocore)."""


class S3Storage:
    """Files in an S3-compatible storage (MinIO in docker-compose).

    The bucket is public-read, so `url()` builds a plain link instead of a signed (presigned) one.
    """

    def __init__(self, endpoint_url: str, public_url: str, access_key: str, secret_key: str, bucket: str):
        self._endpoint_url = endpoint_url
        self._public_url = public_url.rstrip("/")
        self._bucket = bucket
        self._session = aioboto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key)

    def _client(self):
        return self._session.client("s3", endpoint_url=self._endpoint_url, region_name="us-east-1")

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as s3:
                await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as error:
            raise StorageError(f"Failed to upload {key}: {error}") from error

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise StorageError(f"Failed to delete {key}: {error}") from error

    def url(self, key: str) -> str:
        return f"{self._public_url}/{self._bucket}/{key}"
