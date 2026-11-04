from datetime import timedelta
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]

SYNC_DRIVERS = {"postgresql+asyncpg": "postgresql+psycopg"}


def to_sync_url(async_url: str) -> str:
    url = make_url(async_url)
    return url.set(drivername=SYNC_DRIVERS.get(url.drivername, url.drivername)).render_as_string(hide_password=False)


class Settings(BaseSettings):
    # --- Application ---
    BASE_DIR: Path = BASE_DIR
    APP_TITLE: str = "Movie API"
    APP_DESCRIPTION: str = "Movie API"
    APP_VERSION: str = "1.0.0"
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    API_VERSION_PREFIX: str = "/api/v1"

    # --- Database ---
    DATABASE_URL: str
    DB_ECHO: bool = False

    # --- Stripe ---
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_SUCCESS_URL: str
    STRIPE_CANCEL_URL: str

    # --- Celery ---
    BROKER_URL: str = "redis://localhost:6379"

    # --- Auth: JWT and tokens ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_LIFETIME: timedelta = timedelta(hours=1)
    REFRESH_TOKEN_LIFETIME: timedelta = timedelta(hours=48)
    PASSWORD_RESET_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    ACTIVATION_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    REFRESH_TOKEN_NBYTES: int = 48
    PASSWORD_RESET_TOKEN_NBYTES: int = 32
    ACTIVATION_TOKEN_NBYTES: int = 32

    # --- Auth: password policy ---
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_SPECIAL_CHARS: str = "@$!%*?&#"

    # --- Docs (served under API_VERSION_PREFIX, behind HTTP Basic) ---
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    OPENAPI_URL: str = "/openapi.json"

    # --- Email ---
    EMAIL_HOSTNAME: str
    EMAIL_PORT: int
    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_USE_TLS: bool
    TEMPLATE_DIR: Path = BASE_DIR / "src" / "notifications" / "templates"
    ACTIVATION_COMPLETE_TEMPLATE_NAME: str = "activation_complete.html"
    ACTIVATION_REQUEST_TEMPLATE_NAME: str = "activation_request.html"
    PASSWORD_RESET_REQUEST_TEMPLATE_NAME: str = "password_reset_request.html"
    PASSWORD_RESET_COMPLETE_TEMPLATE_NAME: str = "password_reset_complete.html"
    COMMENT_REPLY_TEMPLATE_NAME: str = "comment_reply.html"
    COMMENT_LIKE_TEMPLATE_NAME: str = "comment_like.html"
    ACTIVATION_REQUEST_SUBJECT: str = "Account Activation"
    ACTIVATION_COMPLETE_SUBJECT: str = "Account Activated Successfully"
    PASSWORD_RESET_REQUEST_SUBJECT: str = "Password Reset Request"
    PASSWORD_RESET_COMPLETE_SUBJECT: str = "Your Password Has Been Successfully Reset"
    COMMENT_REPLY_SUBJECT: str = "New Reply to Your Comment"
    COMMENT_LIKE_SUBJECT: str = "Someone Liked Your Comment"

    # --- File storage (S3 API: MinIO in docker-compose) ---
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_PUBLIC_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str = "avatars"
    ORPHAN_AVATAR_MIN_AGE: timedelta = timedelta(hours=1)

    # --- Profiles: avatar ---
    AVATAR_MAX_SIZE: int = 1024 * 1024
    AVATAR_FORMATS: tuple[str, ...] = ("JPEG", "PNG")

    # --- Movies: pagination ---
    PAGINATION_DEFAULT_PER_PAGE: int = 10
    PAGINATION_MAX_PER_PAGE: int = 20

    # --- Tests ---
    TEST_DATABASE_URL: str = "postgresql+asyncpg://cinema:cinema@localhost:5432/cinema_test"
    TEST_DB_ECHO: bool = False

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    @property
    def SYNC_DATABASE_URL(self) -> str:
        return to_sync_url(self.DATABASE_URL)

    @property
    def SECURITY_TOKEN_URL(self) -> str:
        return f"{self.API_VERSION_PREFIX}/security"

    @property
    def ACTIVATION_LINK_BASE(self) -> str:
        return f"{self.API_VERSION_PREFIX}/accounts/activate"

    @property
    def PASSWORD_RESET_LINK_BASE(self) -> str:
        return f"{self.API_VERSION_PREFIX}/accounts/password_reset"

    @property
    def ACTIVATION_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.ACTIVATION_LINK_BASE}"

    @property
    def PASSWORD_RESET_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.PASSWORD_RESET_LINK_BASE}"

    @property
    def LOGIN_LINK_ENDPOINT(self) -> str:
        return f"{self.FRONTEND_URL.rstrip('/')}/login"


settings = Settings()
