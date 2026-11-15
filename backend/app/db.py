"""Підключення до БД (PostgreSQL 16 у docker, SQLite — для локальних тестів)."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal: sessionmaker | None = None


def configure(url: str | None = None) -> None:
    """(Пере)створює engine; викликається при старті та в тестах."""
    global engine, SessionLocal
    url = url or settings.database_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


def is_postgres() -> bool:
    return engine is not None and engine.dialect.name == "postgresql"


def get_session() -> Iterator[Session]:
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


configure()
