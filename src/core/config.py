from datetime import timedelta
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # --- Application ---
    BASE_DIR: Path = BASE_DIR
    APP_TITLE: str = "Movie API"
    APP_DESCRIPTION: str = "Movie API"
    APP_VERSION: str = "1.0.0"
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    API_VERSION_PREFIX: str = "/api/v1"

    # --- Database ---
    # Async SQLAlchemy URL. Leave empty to use a local SQLite file at DB_PATH.
    # For PostgreSQL: postgresql+asyncpg://user:password@host:5432/dbname
    DATABASE_URL: str = ""
    DB_PATH: Path = BASE_DIR / "cinema.db"
    DB_ECHO: bool = False

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
    TEST_DATABASE_URL: str = "sqlite+aiosqlite://"
    TEST_DB_ECHO: bool = False

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    @model_validator(mode="after")
    def _default_database_url(self) -> "Settings":
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite+aiosqlite:///{self.DB_PATH.as_posix()}"
        return self


    @property
    def SYNC_DATABASE_URL(self) -> str:
        sync_drivers = {"sqlite+aiosqlite": "sqlite", "postgresql+asyncpg": "postgresql+psycopg"}
        url = make_url(self.DATABASE_URL)
        return url.set(drivername=sync_drivers.get(url.drivername, url.drivername)).render_as_string(hide_password=False)


    @property
    def ACTIVATION_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.ACTIVATION_LINK_BASE}"

    @property
    def PASSWORD_RESET_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.PASSWORD_RESET_LINK_BASE}"

    @property
    def LOGIN_LINK_ENDPOINT(self) -> str:
        return f"{self.APP_BASE_URL}{self.SECURITY_TOKEN_URL}/token"


settings = Settings()
