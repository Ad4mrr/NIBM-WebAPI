"""Database engine, session factory, and FastAPI session dependency."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for common PostgreSQL URLs supplied by hosting services."""

    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create an engine that works with local SQLite or deployed PostgreSQL."""

    settings = get_settings()
    url = normalize_database_url(database_url or settings.database_url)
    parsed_url = make_url(url)

    engine_options: dict[str, Any] = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }

    if parsed_url.get_backend_name() == "sqlite":
        # FastAPI may use sessions from worker threads during local development.
        engine_options["connect_args"] = {"check_same_thread": False}
        if parsed_url.database in {None, "", ":memory:"}:
            # All sessions must share one connection for an in-memory test database.
            engine_options["poolclass"] = StaticPool

    database_engine = create_engine(url, **engine_options)

    if parsed_url.get_backend_name() == "sqlite":

        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            # SQLite does not enforce declared foreign keys unless this is enabled.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return database_engine


def create_session_factory(database_engine: Engine) -> sessionmaker[Session]:
    """Build a session factory with predictable API-friendly behaviour."""

    return sessionmaker(
        bind=database_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


engine = create_database_engine()
SessionLocal = create_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    """Yield one SQLAlchemy session for a request and always close it."""

    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()


def init_db(database_engine: Engine = engine) -> None:
    """Create tables for local use; production deployments should use migrations."""

    # Imported here to keep the model module independent from engine creation.
    from .models import Base

    Base.metadata.create_all(bind=database_engine)
