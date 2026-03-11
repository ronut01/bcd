"""Database helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from bcd.config import Settings, get_settings


_ENGINE_CACHE: dict[str, object] = {}


def _prepare_sqlite_path(database_url: str) -> None:
    if not database_url.startswith("sqlite:///") or database_url.endswith(":memory:"):
        return
    raw_path = database_url.removeprefix("sqlite:///")
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def get_engine(database_url: str | None = None):
    """Create or return a cached SQLModel engine."""

    settings = get_settings()
    target_url = database_url or settings.database_url
    if target_url in _ENGINE_CACHE:
        return _ENGINE_CACHE[target_url]

    _prepare_sqlite_path(target_url)
    engine_kwargs = {"echo": False}
    if target_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    if target_url.endswith(":memory:"):
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(target_url, **engine_kwargs)
    _ENGINE_CACHE[target_url] = engine
    return engine


def init_db(settings: Settings | None = None) -> None:
    """Create all SQLModel tables for the configured database."""

    active_settings = settings or get_settings()
    engine = get_engine(active_settings.database_url)
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(database_url: str | None = None):
    """Open a short-lived database session."""

    session = Session(get_engine(database_url))
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
