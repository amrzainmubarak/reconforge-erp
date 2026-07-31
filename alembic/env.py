"""Alembic environment for the optional PostgreSQL server schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config
if config.config_file_name is not None:
    # Migrations can run inside the API/operator process. Preserve application
    # audit loggers instead of letting dictConfig disable every existing logger.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Read a PostgreSQL URL without allowing credentials in repository config."""

    raw = os.environ.get("RECONFORGE_POSTGRES_DSN", "").strip()
    if not raw:
        raise RuntimeError("RECONFORGE_POSTGRES_DSN must be set for PostgreSQL migrations.")
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw.removeprefix("postgres://")
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw.removeprefix("postgresql://")
    if not raw.startswith("postgresql+"):
        raise RuntimeError("RECONFORGE_POSTGRES_DSN must be a PostgreSQL SQLAlchemy URL.")
    return raw


database_url = _database_url()
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = None


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a bounded SQLAlchemy connection."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
