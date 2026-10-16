"""Настройки приложения.

pydantic-settings читает значения из переменных окружения и файла .env.
Так конфиг не "зашит" в код: для другой БД достаточно поменять DATABASE_URL.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Online Cinema API"
    # По умолчанию SQLite-файл в корне проекта: ничего не нужно устанавливать.
    # Для PostgreSQL: postgresql+psycopg://user:password@localhost:5432/cinema
    database_url: str = "sqlite:///./cinema.db"


settings = Settings()
