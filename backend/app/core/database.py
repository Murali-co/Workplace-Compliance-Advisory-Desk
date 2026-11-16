"""Neon PostgreSQL connections; schema changes use explicit migrations."""

from functools import lru_cache

import app.models.compliance  # noqa: F401
from app.core.config import settings
from app.models.base import Base
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def database_options(raw: str):
    try:
        url = make_url(raw)
        if url.get_backend_name() != "postgresql" or not (url.host or "").endswith(".neon.tech"):
            raise ValueError()
        query = dict(url.query)
        mode = query.pop("sslmode", "require")
        if mode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError()
        if any(k in query for k in ("host", "hostaddr", "port", "dbname", "ssl")):
            raise ValueError()
        query.pop("channel_binding", None)
        return url.set(drivername="postgresql+asyncpg", query=query), {"ssl": mode, "timeout": 5}
    except Exception:
        raise ValueError(
            "Configure a Neon PostgreSQL DATABASE_URL with TLS; credentials redacted."
        ) from None


@lru_cache
def get_engine():
    url, options = database_options(settings.DATABASE_URL)
    if settings.DATABASE_DNS_RESOLVER == "cloudflare":
        from app.core.neon_dns import connect_neon

        return create_async_engine(
            url.set(drivername="postgresql+psycopg"),
            async_creator=lambda: connect_neon(url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_recycle=240,
            echo=False,
            hide_parameters=True,
        )
    return create_async_engine(
        url,
        connect_args=options,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
        hide_parameters=True,
    )


def async_session_maker():
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)()


async def get_db():
    from fastapi import HTTPException

    try:
        session = async_session_maker()
    except ValueError:
        raise HTTPException(503, "Data service has not been configured.") from None
    async with session:
        yield session


async def init_db():
    """Explicit isolated bootstrap helper; never called during API startup."""
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
