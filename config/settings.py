import os
from pathlib import Path

from pydantic_settings import BaseSettings




class BaseAppSettings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent
    DB_PATH: Path = BASE_DIR /"src" / "db" / 'cinema.db'
