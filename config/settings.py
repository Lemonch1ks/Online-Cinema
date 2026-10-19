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
    SECURITY_TOKEN_URL: str = API_VERSION_PREFIX + "/security/token"

    SECRET_KEY: str
    ALGORITHM: str

    model_config = SettingsConfigDict(env_file=".env")

base_app_settings = BaseAppSettings()
