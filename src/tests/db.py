"""Helpers to create, migrate and drop throwaway PostgreSQL databases for tests."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.core.config import BASE_DIR, to_sync_url


def with_database(url: str, database: str) -> str:
    """Same server and credentials, another database name."""
    return make_url(url).set(database=database).render_as_string(hide_password=False)


def _admin_engine(url: str):
    # CREATE / DROP DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    # Connect to the maintenance db "postgres", you cannot drop the db you are connected to.
    return create_engine(to_sync_url(with_database(url, "postgres")), isolation_level="AUTOCOMMIT")


def create_database(url: str) -> None:
    """(Re)create an empty database. Dropping first cleans up after a crashed previous run."""
    name = make_url(url).database
    engine = _admin_engine(url)
    with engine.connect() as conn:
        # FORCE closes leftover connections (PostgreSQL 13+)
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


def drop_database(url: str) -> None:
    name = make_url(url).database
    engine = _admin_engine(url)
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    engine.dispose()


def alembic(url: str, *commands: tuple[str, str]) -> None:
    """Run alembic commands, e.g. ("upgrade", "head"), against the given database.

    Config is built from pyproject.toml only (no alembic.ini): alembic.ini would run logging.fileConfig,
    which disables already created loggers and breaks pytest's caplog.
    """
    config = Config(toml_file=str(BASE_DIR / "pyproject.toml"))
    engine = create_engine(to_sync_url(url))
    with engine.begin() as connection:
        config.attributes["connection"] = connection  # picked up by alembic/env.py
        for name, revision in commands:
            getattr(command, name)(config, revision)
    engine.dispose()
