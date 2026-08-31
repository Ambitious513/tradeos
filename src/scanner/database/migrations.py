"""Minimal metadata-based schema creation for development and tests."""

from sqlalchemy.ext.asyncio import AsyncEngine

from scanner.database.models import Base
from scanner.logging_setup import get_logger

logger = get_logger("database.migrations")


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create all registered tables, safely preserving existing tables."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, checkfirst=True)
    logger.info("database_tables_created")
