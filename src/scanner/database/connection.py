"""Async SQLAlchemy engine and session management."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scanner.logging_setup import get_logger

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./scanner.db"
logger = get_logger("database.connection")


def get_database_url() -> str:
    """Return the configured database URL without exposing credentials in logs."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an asynchronous SQLAlchemy engine for a database URL."""
    resolved_url = database_url or get_database_url()
    logger.info(
        "database_engine_created", database_dialect=resolved_url.split(":", 1)[0]
    )
    return create_async_engine(resolved_url)


_engine = create_engine()
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a transactional async session and roll it back on failure."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("database_session_failed")
            raise
