from datetime import timedelta
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent
    DB_PATH: Path = BASE_DIR /"src" / "db" / 'cinema.db'
    REFRESH_TOKEN_LIFETIME: timedelta = timedelta(hours=48)
    ACCESS_TOKEN_LIFETIME: timedelta = timedelta(hours=1)
    PASSWORD_RESET_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    ACTIVATION_TOKEN_LIFETIME: timedelta = timedelta(hours=24)

    API_VERSION_PREFIX: str = "/api/v1"
    SECURITY_TOKEN_URL: str = API_VERSION_PREFIX + "/security"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"

    ACTIVATION_LINK_BASE: str = API_VERSION_PREFIX + "/accounts/activate/"

    EMAIL_HOSTNAME: str
    EMAIL_PORT: int
    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_USE_TLS: bool
    TEMPLATE_DIR: Path = BASE_DIR / "src" / "notifications" /"templates"
    ACTIVATION_COMPLETE_TEMPLATE_NAME: str = "activation_complete.html"
    ACTIVATION_REQUEST_TEMPLATE_NAME: str = "activation_request.html"
    PASSWORD_RESET_REQUEST_TEMPLATE_NAME: str = "password_reset_request.html"
    PASSWORD_RESET_COMPLETE_TEMPLATE_NAME: str = "password_reset_complete.html"

    model_config = SettingsConfigDict(env_file=".env")

base_app_settings = BaseAppSettings()
