"""Mocked unit tests for the Bybit public WebSocket kline transport."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from scanner.config import ScannerConfig
from scanner.market_data.bybit_ws import (
    MAINNET_WS_URL,
    TESTNET_WS_URL,
    BybitWebSocketClient,
)
from scanner.market_data.stale_detector import StaleStreamDetector
from scanner.models import Candle

FIXTURES_DIRECTORY = Path(__file__).parents[1] / "fixtures"


def fixture_message(name: str) -> str:
    """Load one synthetic WebSocket message fixture as a JSON string."""
    return (FIXTURES_DIRECTORY / name).read_text(encoding="utf-8")


async def noop_callback(_: Candle) -> None:
    """Accept a candle without side effects."""


class FakeWebSocket:
    """A controllable asynchronous public WebSocket test transport."""

    def __init__(self, messages: list[object] | None = None) -> None:
        """Create a transport that returns queued messages or raises queued errors."""
        self._messages = list(messages or [])
        self._closed_event = asyncio.Event()
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        """Record a serialized outbound message."""
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        """Return the next queued item or await indefinitely until cancellation."""
        if self._messages:
            item = self._messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, bytes | str):
                return item
            raise TypeError("unsupported fake message")
        await self._closed_event.wait()
        raise OSError("fake transport closed")

    async def close(self) -> None:
        """Mark the transport as closed."""
        self.closed = True
        self._closed_event.set()


def test_client_init_default() -> None:
    """Default settings create a testnet public WebSocket client."""
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    assert client.url == TESTNET_WS_URL
    assert client.is_connected is False


def test_uses_testnet_url() -> None:
    """Testnet configuration never selects the mainnet endpoint."""
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    assert client.url == TESTNET_WS_URL
    assert client.url != MAINNET_WS_URL


def test_mainnet_blocked_in_non_live_env() -> None:
    """Paper and development modes cannot silently connect to mainnet."""
    with pytest.raises(RuntimeError, match="requires environment='live'"):
        BybitWebSocketClient(
            ScannerConfig(_env_file=None, bybit_testnet=False, environment="paper"),
            noop_callback,
        )


@pytest.mark.asyncio
async def test_closed_candle_parsed_and_emitted() -> None:
    """A confirmed Bybit message emits a closed Candle."""
    received: list[Candle] = []

    async def capture(candle: Candle) -> None:
        received.append(candle)

    client = BybitWebSocketClient(ScannerConfig(_env_file=None), capture)
    await client._handle_raw_message(fixture_message("bybit_ws_kline_closed.json"))
    assert received[0].is_closed is True
    assert received[0].symbol == "SOLUSDT"


@pytest.mark.asyncio
async def test_forming_candle_parsed_and_emitted() -> None:
    """A forming update is deliberately emitted for T005 state tracking."""
    received: list[Candle] = []

    async def capture(candle: Candle) -> None:
        received.append(candle)

    client = BybitWebSocketClient(ScannerConfig(_env_file=None), capture)
    await client._handle_raw_message(fixture_message("bybit_ws_kline_message.json"))
    assert received[0].is_closed is False


@pytest.mark.asyncio
async def test_invalid_candle_ohlc_violation_discarded() -> None:
    """Invalid OHLC data is never forwarded to the callback and is CRITICAL."""
    message = json.loads(fixture_message("bybit_ws_kline_closed.json"))
    message["data"][0]["high"] = "100"  # type: ignore[index]
    callback = AsyncMock()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), callback)
    with capture_logs() as logs:
        await client._handle_raw_message(json.dumps(message))
    callback.assert_not_awaited()
    assert any(
        entry["event"] == "candle_ohlc_violation"
        and entry["log_level"] == "critical"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_invalid_candle_not_forwarded_to_callback() -> None:
    """Negative volume is a general validation failure and cannot reach T005."""
    message = json.loads(fixture_message("bybit_ws_kline_closed.json"))
    message["data"][0]["volume"] = "-1"  # type: ignore[index]
    callback = AsyncMock()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), callback)
    with capture_logs() as logs:
        await client._handle_raw_message(json.dumps(message))
    callback.assert_not_awaited()
    assert any(
        entry["event"] == "candle_validation_failed"
        and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_disconnect_triggers_reconnect() -> None:
    """A transport disconnect creates a new public WebSocket connection."""
    first = FakeWebSocket([OSError("network down")])
    second = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    client._sleep_before_reconnect = AsyncMock()  # type: ignore[method-assign]
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect",
        new=AsyncMock(side_effect=[first, second]),
    ) as connect:
        run_task = asyncio.create_task(client.run_forever())
        while connect.await_count < 2:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    assert connect.await_count == 2


@pytest.mark.asyncio
async def test_reconnect_resubscribes_all_topics() -> None:
    """Every prior topic is included in the subscription sent after reconnect."""
    first = FakeWebSocket([OSError("network down")])
    second = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    await client.subscribe(["SOLUSDT"], ["60", "240"])
    client._sleep_before_reconnect = AsyncMock()  # type: ignore[method-assign]
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect",
        new=AsyncMock(side_effect=[first, second]),
    ) as connect:
        run_task = asyncio.create_task(client.run_forever())
        while connect.await_count < 2:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    subscriptions = [json.loads(message) for message in second.sent]
    assert subscriptions[0]["args"] == ["kline.240.SOLUSDT", "kline.60.SOLUSDT"]


@pytest.mark.asyncio
async def test_ping_pong_sent_on_schedule() -> None:
    """Heartbeat processes kline updates while it waits for its matching pong."""
    websocket = FakeWebSocket(
        [fixture_message("bybit_ws_kline_message.json"), '{"op": "pong"}']
    )
    received: list[Candle] = []

    async def capture(candle: Candle) -> None:
        received.append(candle)

    client = BybitWebSocketClient(ScannerConfig(_env_file=None), capture)
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect", new=AsyncMock(return_value=websocket)
    ), patch("scanner.market_data.bybit_ws.PING_INTERVAL_SECONDS", 0.0):
        receive_task = asyncio.create_task(client.run_forever())
        while not websocket.sent:
            await asyncio.sleep(0)
        await client.stop()
        await receive_task
    assert json.loads(websocket.sent[0]) == {"op": "ping"}
    assert received[0].is_closed is False


@pytest.mark.asyncio
async def test_pong_timeout_triggers_reconnect() -> None:
    """Missing pong causes a disconnect and another transport connection."""
    first = FakeWebSocket()
    second = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    client._sleep_before_reconnect = AsyncMock()  # type: ignore[method-assign]
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect",
        new=AsyncMock(side_effect=[first, second]),
    ) as connect, patch("scanner.market_data.bybit_ws.PING_INTERVAL_SECONDS", 0.0), patch(
        "scanner.market_data.bybit_ws.PONG_TIMEOUT_SECONDS", 0.001
    ):
        run_task = asyncio.create_task(client.run_forever())
        while connect.await_count < 2:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    assert connect.await_count >= 2


def test_stale_detector_record_and_query() -> None:
    """A freshly recorded stream topic is not stale."""
    detector = StaleStreamDetector(max_silence_seconds=70)
    with patch("scanner.market_data.stale_detector.time.monotonic", return_value=100.0):
        detector.record_message("SOLUSDT", "60")
    with patch("scanner.market_data.stale_detector.time.monotonic", return_value=101.0):
        assert detector.get_stale_topics() == []


def test_stale_detector_is_stale_after_silence() -> None:
    """A stream exceeds its configured silence budget after the threshold."""
    detector = StaleStreamDetector(max_silence_seconds=10)
    with patch("scanner.market_data.stale_detector.time.monotonic", return_value=100.0):
        detector.record_message("SOLUSDT", "60")
    with patch("scanner.market_data.stale_detector.time.monotonic", return_value=111.0):
        assert detector.is_stale("SOLUSDT", "60") is True


def test_stale_detector_btc_stale_logs_error() -> None:
    """BTC 4H stream staleness is explicitly escalated for regime safety."""
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    with patch("scanner.market_data.stale_detector.time.monotonic", return_value=1.0):
        client._stale_detector.watch_topic("BTCUSDT", "240")
    with patch(
        "scanner.market_data.stale_detector.time.monotonic", return_value=100.0
    ), capture_logs() as logs:
        client._log_stale_topics()
    assert any(
        entry["event"] == "btc_4h_topic_stale" and entry["log_level"] == "error"
        for entry in logs
    )


@pytest.mark.asyncio
async def test_callback_exception_does_not_crash_loop() -> None:
    """A callback failure is isolated and the next message remains processable."""
    calls = 0

    async def broken_callback(_: Candle) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("consumer failure")

    client = BybitWebSocketClient(ScannerConfig(_env_file=None), broken_callback)
    with capture_logs() as logs:
        await client._handle_raw_message(fixture_message("bybit_ws_kline_closed.json"))
        await client._handle_raw_message(fixture_message("bybit_ws_kline_closed.json"))
    assert calls == 2
    assert any(entry["event"] == "candle_callback_error" for entry in logs)


@pytest.mark.asyncio
async def test_stop_exits_run_forever() -> None:
    """Stopping an active client closes its transport and returns its run task."""
    websocket = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect", new=AsyncMock(return_value=websocket)
    ):
        run_task = asyncio.create_task(client.run_forever())
        while not client.is_connected:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_structured_log_on_connect() -> None:
    """Successful connection emits the expected structured log event."""
    websocket = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect", new=AsyncMock(return_value=websocket)
    ), capture_logs() as logs:
        run_task = asyncio.create_task(client.run_forever())
        while not client.is_connected:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    assert any(entry["event"] == "websocket_connected" for entry in logs)


@pytest.mark.asyncio
async def test_structured_log_on_disconnect() -> None:
    """A disconnect emits the expected warning-level structured event."""
    first = FakeWebSocket([OSError("network down")])
    second = FakeWebSocket()
    client = BybitWebSocketClient(ScannerConfig(_env_file=None), noop_callback)
    client._sleep_before_reconnect = AsyncMock()  # type: ignore[method-assign]
    with patch(
        "scanner.market_data.bybit_ws.websockets.connect",
        new=AsyncMock(side_effect=[first, second]),
    ) as connect, capture_logs() as logs:
        run_task = asyncio.create_task(client.run_forever())
        while connect.await_count < 2:
            await asyncio.sleep(0)
        await client.stop()
        await run_task
    assert any(
        entry["event"] == "websocket_disconnect_detected"
        and entry["log_level"] == "warning"
        for entry in logs
    )
