"""Alembic environment.

Reads DATABASE_URL from app.config and binds Alembic to the
SQLAlchemy metadata in app.db.base for autogeneration.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

# Match app.main: psycopg async needs SelectorEventLoop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alembic import context  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy.engine import Connection  # noqa: E402
from sqlalchemy.ext.asyncio import async_engine_from_config  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# Import models so their tables are registered on Base.metadata.
from app.db import models  # noqa: F401, E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("+psycopg", "+psycopg_async"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
