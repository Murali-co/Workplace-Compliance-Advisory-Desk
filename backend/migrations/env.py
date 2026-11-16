"""Migrations use the same TLS-validated Neon configuration as the application."""

import asyncio

from alembic import context
from app.core.database import get_engine


def run(connection):
    context.configure(connection=connection, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = get_engine()
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url="postgresql://", literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
