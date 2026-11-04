from functools import lru_cache

from src.core.config import settings
from src.storage.s3 import S3Storage


@lru_cache
def get_storage() -> S3Storage:
    return S3Storage(
        endpoint_url=settings.S3_ENDPOINT_URL,
        public_url=settings.S3_PUBLIC_URL,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        bucket=settings.S3_BUCKET,
    )
