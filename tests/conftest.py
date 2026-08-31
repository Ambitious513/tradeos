"""Shared fixtures for A+ Scanner tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from scanner.config import ScannerConfig
from scanner.database.migrations import create_all_tables
from scanner.models import Candle


@pytest.fixture
def config() -> ScannerConfig:
    """Provide settings with explicit safe defaults and no local .env dependency."""
    return ScannerConfig(_env_file=None)


@pytest.fixture
async def db_engine() -> AsyncEngine:
    """Provide a fresh in-memory SQLite engine with the full schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncSession:
    """Provide an async session bound to the in-memory test database."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def sample_candle() -> Callable[[bool], Candle]:
    """Provide a valid closed 1H altcoin candle factory."""

    def factory(is_closed: bool = True) -> Candle:
        return Candle(
            symbol="ETHUSDT",
            timeframe="60",
            open_time=datetime(2026, 8, 31, tzinfo=UTC),
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("99.00"),
            close=Decimal("103.00"),
            volume=Decimal("2500"),
            turnover=Decimal("257500"),
            is_closed=is_closed,
        )

    return factory


@pytest.fixture
def sample_btc_candle() -> Callable[[bool], Candle]:
    """Provide a valid closed BTC/USDT 4H candle factory."""

    def factory(is_closed: bool = True) -> Candle:
        return Candle(
            symbol="BTCUSDT",
            timeframe="240",
            open_time=datetime(2026, 8, 31, tzinfo=UTC),
            open=Decimal("110000.00"),
            high=Decimal("112000.00"),
            low=Decimal("109000.00"),
            close=Decimal("111000.00"),
            volume=Decimal("1000"),
            turnover=Decimal("111000000"),
            is_closed=is_closed,
        )

    return factory
