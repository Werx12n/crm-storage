"""Alembic: міграції схеми БД WMS. URL береться з DATABASE_URL (app.config)."""
from alembic import context

from app import db
import app.entities  # noqa: F401  — реєстрація моделей у metadata

target_metadata = db.Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=str(db.engine.url), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
