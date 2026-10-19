from datetime import timedelta
from pathlib import Path

from pydantic_settings import BaseSettings


class BaseAppSettings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent
    DB_PATH: Path = BASE_DIR /"src" / "db" / 'cinema.db'
    REFRESH_TOKEN_LIFETIME: timedelta = timedelta(hours=48)
    PASSWORD_RESET_TOKEN_LIFETIME: timedelta = timedelta(hours=24)
    ACTIVATION_TOKEN_LIFETIME: timedelta = timedelta(hours=24)


base_app_settings = BaseAppSettings()
