"""Unit tests for the cached Bybit trading-symbol universe."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from scanner.candle_store.universe_manager import UniverseManager, UniverseRefreshError
from scanner.config import ScannerConfig
from scanner.market_data.bybit_rest import BybitAPIError
from scanner.market_data.models import Ticker24H

FIXTURES_DIRECTORY = Path(__file__).parents[1] / "fixtures"


def fixture_tickers() -> list[Ticker24H]:
    """Build normalized ticker values from the synthetic universe fixture."""
    payload = json.loads(
        (FIXTURES_DIRECTORY / "bybit_tickers_universe.json").read_text(encoding="utf-8")
    )
    rows = payload["result"]["list"]
    return [
        Ticker24H(
            symbol=row["symbol"],
            last_price=Decimal("1"),
            high_24h=Decimal("1"),
            low_24h=Decimal("1"),
            volume_24h=Decimal("1"),
            turnover_24h=Decimal(row["turnover24h"]),
            price_change_pct_24h=0.0,
            timestamp=datetime.now(UTC),
        )
        for row in rows
    ]


def manager_with_tickers() -> tuple[UniverseManager, AsyncMock]:
    """Return a manager backed by a mocked ticker transport."""
    rest_client = AsyncMock()
    rest_client.get_tickers_24h.return_value = fixture_tickers()
    return UniverseManager(rest_client, ScannerConfig(_env_file=None)), rest_client


@pytest.mark.asyncio
async def test_volume_filter_applied() -> None:
    """Only USDT tickers meeting the approved turnover threshold are selected."""
    manager, _ = manager_with_tickers()
    symbols = await manager.refresh()
    assert "LOWUSDT" not in symbols
    assert "BTCUSD" not in symbols
    assert {"ETHUSDT", "SOLUSDT", "XRPUSDT"}.issubset(symbols)


@pytest.mark.asyncio
async def test_btc_always_included_below_threshold() -> None:
    """BTC remains available for regime data even with negligible turnover."""
    manager, _ = manager_with_tickers()
    assert "BTCUSDT" in await manager.refresh()


@pytest.mark.asyncio
async def test_symbols_sorted_alphabetically() -> None:
    """Consumers receive the cached universe in a deterministic order."""
    manager, _ = manager_with_tickers()
    assert await manager.refresh() == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


@pytest.mark.asyncio
async def test_refresh_failure_returns_cache() -> None:
    """A failed refresh safely preserves and returns the prior universe."""
    manager, rest_client = manager_with_tickers()
    cached = await manager.refresh()
    rest_client.get_tickers_24h.side_effect = BybitAPIError("unavailable")
    with capture_logs() as logs:
        assert await manager.refresh() == cached
    assert any(
        entry["event"] == "universe_refresh_used_cache"
        and entry["log_level"] == "warning"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_refresh_failure_no_cache_raises_universe_refresh_error() -> None:
    """No cached universe turns a transport failure into the stable domain error."""
    manager, rest_client = manager_with_tickers()
    rest_client.get_tickers_24h.side_effect = BybitAPIError("unavailable")
    with capture_logs() as logs, pytest.raises(UniverseRefreshError):
        await manager.refresh()
    assert any(
        entry["event"] == "universe_refresh_failed_no_cache"
        and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_last_refreshed_at_set_on_success() -> None:
    """Successful refreshes record a timezone-aware timestamp."""
    manager, _ = manager_with_tickers()
    await manager.refresh()
    assert manager.last_refreshed_at is not None
    assert manager.last_refreshed_at.tzinfo is UTC


def test_last_refreshed_at_none_before_first_refresh() -> None:
    """A newly created manager has no refresh timestamp."""
    manager, _ = manager_with_tickers()
    assert manager.last_refreshed_at is None
