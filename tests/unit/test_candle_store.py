"""Unit tests for the in-memory closed-candle buffer."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from scanner.candle_store.candle_store import CandleStore
from scanner.config import ScannerConfig
from scanner.market_data.bybit_rest import BybitAPIError
from scanner.models import Candle

BASE_TIME = datetime(2026, 8, 31, tzinfo=UTC)


def candle(
    offset_hours: int,
    *,
    symbol: str = "SOLUSDT",
    interval: str = "60",
    is_closed: bool = True,
) -> Candle:
    """Create a minimal valid synthetic candle at a predictable UTC time."""
    return Candle(
        symbol=symbol,
        timeframe=interval,
        open_time=BASE_TIME + timedelta(hours=offset_hours),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        is_closed=is_closed,
    )


def store_with_mocks(
    buffer_size: int = 200,
) -> tuple[CandleStore, AsyncMock, AsyncMock]:
    """Return a store with mocked REST and WebSocket clients."""
    rest_client = AsyncMock()
    ws_client = AsyncMock()
    return (
        CandleStore(rest_client, ws_client, ScannerConfig(_env_file=None), buffer_size),
        rest_client,
        ws_client,
    )


@pytest.mark.asyncio
async def test_prefill_populates_buffer_oldest_first() -> None:
    """REST pre-fill orders returned history for downstream consumers."""
    store, rest_client, _ = store_with_mocks()
    rest_client.get_klines.return_value = [candle(2), candle(0), candle(1)]
    await store.initialize(["SOLUSDT"], ["60"])
    assert [
        item.open_time for item in store.get_closed_candles("SOLUSDT", "60", 3)
    ] == [
        candle(0).open_time,
        candle(1).open_time,
        candle(2).open_time,
    ]


@pytest.mark.asyncio
async def test_btc_prefill_failure_logs_error() -> None:
    """BTC pre-fill failure is elevated because it blocks regime calculation."""
    store, rest_client, _ = store_with_mocks()
    rest_client.get_klines.side_effect = BybitAPIError("unavailable")
    with capture_logs() as logs:
        await store.initialize(["BTCUSDT"], ["240"])
    assert any(
        entry["event"] == "btc_prefill_failed" and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_non_btc_prefill_failure_logs_warning_continues() -> None:
    """One failed altcoin pre-fill leaves initialization operational."""
    store, rest_client, ws_client = store_with_mocks()
    rest_client.get_klines.side_effect = BybitAPIError("unavailable")
    with capture_logs() as logs:
        await store.initialize(["SOLUSDT"], ["60"])
    ws_client.subscribe.assert_awaited_once_with(["SOLUSDT"], ["60"])
    assert any(
        entry["event"] == "prefill_failed" and entry["log_level"] == "warning"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_subscribe_called_after_prefill() -> None:
    """The live subscription begins only after all requested history is fetched."""
    store, rest_client, ws_client = store_with_mocks()
    order: list[str] = []

    async def get_klines(*_: object, **__: object) -> list[Candle]:
        order.append("prefill")
        return []

    async def subscribe(*_: object, **__: object) -> None:
        order.append("subscribe")

    rest_client.get_klines.side_effect = get_klines
    ws_client.subscribe.side_effect = subscribe
    await store.initialize(["SOLUSDT"], ["60"])
    assert order == ["prefill", "subscribe"]


@pytest.mark.asyncio
async def test_forming_candle_not_stored_in_buffer() -> None:
    """Forming updates are retained separately and remain unavailable to strategy."""
    store, _, _ = store_with_mocks()
    forming = candle(0, is_closed=False)
    await store.on_candle(forming)
    assert store.get_closed_candles("SOLUSDT", "60", 1) == []
    assert store.get_forming_candle("SOLUSDT", "60") == forming


@pytest.mark.asyncio
async def test_closed_candle_stored_and_returned() -> None:
    """A confirmed live update becomes visible through the closed-only API."""
    store, _, _ = store_with_mocks()
    confirmed = candle(0)
    await store.on_candle(confirmed)
    assert store.get_closed_candles("SOLUSDT", "60", 1) == [confirmed]


@pytest.mark.asyncio
async def test_get_closed_candles_oldest_first() -> None:
    """Requesting the newest slice preserves chronological order."""
    store, _, _ = store_with_mocks()
    for offset in (2, 0, 1):
        await store.on_candle(candle(offset))
    assert store.get_closed_candles("SOLUSDT", "60", 2) == [candle(1), candle(2)]


def test_get_closed_candles_unknown_symbol_returns_empty() -> None:
    """Unknown symbols are safe empty reads for downstream consumers."""
    store, _, _ = store_with_mocks()
    assert store.get_closed_candles("UNKNOWNUSDT", "60", 10) == []


@pytest.mark.asyncio
async def test_duplicate_candle_same_open_time_rejected() -> None:
    """Repeated updates for a candle do not duplicate the closed history."""
    store, _, _ = store_with_mocks()
    await store.on_candle(candle(0))
    await store.on_candle(candle(0))
    assert store.get_closed_candles("SOLUSDT", "60", 5) == [candle(0)]


@pytest.mark.asyncio
async def test_buffer_evicts_oldest_when_full() -> None:
    """A bounded buffer removes the oldest closed candle first."""
    store, _, _ = store_with_mocks(buffer_size=2)
    for offset in range(3):
        await store.on_candle(candle(offset))
    assert store.get_closed_candles("SOLUSDT", "60", 3) == [candle(1), candle(2)]


@pytest.mark.asyncio
async def test_gap_detected_and_rest_fill_called() -> None:
    """A skipped interval requests REST history ending before the new candle."""
    store, rest_client, _ = store_with_mocks()
    await store.on_candle(candle(0))
    rest_client.get_klines.return_value = []
    await store.on_candle(candle(2))
    rest_client.get_klines.assert_awaited_once_with(
        "SOLUSDT",
        "60",
        limit=6,
        end_time_ms=int(candle(2).open_time.timestamp() * 1_000) - 1,
    )


@pytest.mark.asyncio
async def test_gap_fill_inserts_missing_candles() -> None:
    """REST gap history is deduplicated and placed between existing live updates."""
    store, rest_client, _ = store_with_mocks()
    await store.on_candle(candle(0))
    rest_client.get_klines.return_value = [candle(1)]
    await store.on_candle(candle(2))
    assert store.get_closed_candles("SOLUSDT", "60", 3) == [
        candle(0),
        candle(1),
        candle(2),
    ]


@pytest.mark.asyncio
async def test_gap_fill_failure_logs_error_candle_still_stored() -> None:
    """A failed gap fill never discards the newly confirmed live candle."""
    store, rest_client, _ = store_with_mocks()
    await store.on_candle(candle(0))
    rest_client.get_klines.side_effect = BybitAPIError("unavailable")
    with capture_logs() as logs:
        await store.on_candle(candle(2))
    assert store.get_closed_candles("SOLUSDT", "60", 2) == [candle(0), candle(2)]
    assert any(
        entry["event"] == "gap_fill_failed" and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_no_forming_candle_in_get_closed_candles_output() -> None:
    """Mixed live updates expose only confirmed candles to strategy consumers."""
    store, _, _ = store_with_mocks()
    await store.on_candle(candle(0))
    await store.on_candle(candle(1, is_closed=False))
    assert store.get_closed_candles("SOLUSDT", "60", 2) == [candle(0)]


def test_forming_candle_in_buffer_defensive_logs_error() -> None:
    """Defensive reads reject any invalid forming candle injected into the buffer."""
    store, _, _ = store_with_mocks()
    store._closed_buffers[("SOLUSDT", "60")] = [candle(0, is_closed=False)]
    with capture_logs() as logs:
        assert store.get_closed_candles("SOLUSDT", "60", 1) == []
    assert any(
        entry["event"] == "forming_candle_in_buffer" and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_is_ready_false_when_below_threshold() -> None:
    """Insufficient history prevents strategy warmup."""
    store, _, _ = store_with_mocks()
    await store.on_candle(candle(0))
    assert store.is_ready("SOLUSDT", "60", 2) is False


@pytest.mark.asyncio
async def test_is_ready_true_when_at_or_above_threshold() -> None:
    """Enough closed candles make the requested history ready."""
    store, _, _ = store_with_mocks()
    await store.on_candle(candle(0))
    await store.on_candle(candle(1))
    assert store.is_ready("SOLUSDT", "60", 2) is True


def test_is_ready_false_for_unknown_symbol() -> None:
    """Unknown buffers cannot satisfy any positive readiness requirement."""
    store, _, _ = store_with_mocks()
    assert store.is_ready("UNKNOWNUSDT", "60", 1) is False


@pytest.mark.asyncio
async def test_subscribed_symbols_property() -> None:
    """The subscribed-symbol set reflects successful store initialization."""
    store, rest_client, _ = store_with_mocks()
    rest_client.get_klines.return_value = []
    await store.initialize(["BTCUSDT", "SOLUSDT"], ["60"])
    assert store.subscribed_symbols == frozenset({"BTCUSDT", "SOLUSDT"})
