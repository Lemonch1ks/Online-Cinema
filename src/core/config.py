from datetime import timedelta
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]

# async driver -> sync driver, for Alembic and other sync code
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
    API_VERSION_PREFIX: str = "/api/v1"

    # --- Database ---
    # Required, async driver: postgresql+asyncpg://user:password@host:5432/dbname
    DATABASE_URL: str
    DB_ECHO: bool = False

    #--- Celery ---

    BROKER_URL: str = "redis://localhost:6379"

    # --- Auth: JWT and tokens ---
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    SECURITY_TOKEN_URL: str = API_VERSION_PREFIX + "/security"
    ACCESS_TOKEN_LIFETIME: timedelta = timedelta(hours=1)
    REFRESH_TOKEN_LIFETIME: timedelta = timedelta(hours=48)
    PASSWORD_RESET_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    ACTIVATION_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    # Number of random bytes behind each token (the token string itself is longer: URL-safe base64).
    REFRESH_TOKEN_NBYTES: int = 48
    PASSWORD_RESET_TOKEN_NBYTES: int = 32
    ACTIVATION_TOKEN_NBYTES: int = 32

    # --- Auth: password policy ---
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_SPECIAL_CHARS: str = "@$!%*?&#"

    # --- Links sent in emails ---
    ACTIVATION_LINK_BASE: str = API_VERSION_PREFIX + "/accounts/activate"
    PASSWORD_RESET_LINK_BASE: str = API_VERSION_PREFIX + "/accounts/password_reset"

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
    ACTIVATION_REQUEST_SUBJECT: str = "Account Activation"
    ACTIVATION_COMPLETE_SUBJECT: str = "Account Activated Successfully"
    PASSWORD_RESET_REQUEST_SUBJECT: str = "Password Reset Request"
    PASSWORD_RESET_COMPLETE_SUBJECT: str = "Your Password Has Been Successfully Reset"

    # --- Movies: pagination ---
    PAGINATION_DEFAULT_PER_PAGE: int = 10
    PAGINATION_MAX_PER_PAGE: int = 20

    # --- Tests ---
    # Base URL of the test database. Each pytest(-xdist) worker gets its own copy: <name>_<worker_id>.
    # The default matches the Postgres service from docker-compose.yml.
    TEST_DATABASE_URL: str = "postgresql+asyncpg://cinema:cinema@localhost:5432/cinema_test"
    TEST_DB_ECHO: bool = False

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    @property
    def SYNC_DATABASE_URL(self) -> str:
        return to_sync_url(self.DATABASE_URL)


    @property
    def ACTIVATION_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.ACTIVATION_LINK_BASE}"

    @property
    def PASSWORD_RESET_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.PASSWORD_RESET_LINK_BASE}"

    @property
    def LOGIN_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.SECURITY_TOKEN_URL}/token"


settings = Settings() # type: ignore
