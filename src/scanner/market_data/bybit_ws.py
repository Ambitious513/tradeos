"""Resilient public Bybit V5 WebSocket kline transport.

The client is transport-only: it emits both forming and confirmed candles. Strategy
components must independently reject forming candles before evaluation.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypeAlias

import websockets
from websockets.exceptions import ConnectionClosed

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.stale_detector import StaleStreamDetector
from scanner.models import Candle

TESTNET_WS_URL = "wss://stream-testnet.bybit.com/v5/public/linear"
MAINNET_WS_URL = "wss://stream.bybit.com/v5/public/linear"
PING_INTERVAL_SECONDS = 20.0
PONG_TIMEOUT_SECONDS = 5.0
STALE_CHECK_INTERVAL_SECONDS = 60.0
STOP_WAIT_TIMEOUT_SECONDS = 5.0

logger = get_logger("market_data.ws")

CanvasCallback = Callable[[Candle], Awaitable[None]]
JSONMapping: TypeAlias = Mapping[str, object]


class _WebSocketTransport(Protocol):
    """Minimal async transport required by the public WebSocket client."""

    async def send(self, message: str) -> None:
        """Send a serialized WebSocket message."""

    async def recv(self) -> str | bytes:
        """Receive the next WebSocket message."""

    async def close(self) -> None:
        """Close the WebSocket transport."""


class BybitWebSocketClient:
    """Stream public Bybit linear kline updates with recovery safeguards."""

    def __init__(self, config: ScannerConfig, on_candle: CanvasCallback) -> None:
        """Create a testnet-safe client with an isolated candle callback."""
        if not config.bybit_testnet and config.environment != "live":
            raise RuntimeError(
                "bybit_testnet=False requires environment='live'. "
                "Safety guard against accidental mainnet connections."
            )
        self._url = TESTNET_WS_URL if config.bybit_testnet else MAINNET_WS_URL
        self._on_candle = on_candle
        self._topics: set[str] = set()
        self._stale_detector = StaleStreamDetector()
        self._websocket: _WebSocketTransport | None = None
        self._is_connected = False
        self._stop_requested = False
        self._run_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether a public WebSocket connection is currently active."""
        return self._is_connected

    @property
    def subscribed_topics(self) -> frozenset[str]:
        """Return all desired subscriptions, including those awaiting reconnect."""
        return frozenset(self._topics)

    @property
    def url(self) -> str:
        """Return the selected public WebSocket URL for diagnostics and testing."""
        return self._url

    async def subscribe(self, symbols: list[str], intervals: list[str]) -> None:
        """Subscribe to every requested symbol and timeframe topic."""
        topics = self._topics_for(symbols, intervals)
        self._topics.update(topics)
        for topic in topics:
            _, interval, symbol = topic.split(".", maxsplit=2)
            self._stale_detector.watch_topic(symbol, interval)
        if self._is_connected:
            await self._send_operation("subscribe", topics)

    async def unsubscribe(self, symbols: list[str], intervals: list[str]) -> None:
        """Unsubscribe from requested kline topics and stop tracking their silence."""
        topics = self._topics_for(symbols, intervals)
        self._topics.difference_update(topics)
        for topic in topics:
            _, interval, symbol = topic.split(".", maxsplit=2)
            self._stale_detector.remove_topic(symbol, interval)
        if self._is_connected:
            await self._send_operation("unsubscribe", topics)

    async def run_forever(self) -> None:
        """Connect, stream, and reconnect until :meth:`stop` is called."""
        self._stop_requested = False
        self._run_task = asyncio.current_task()
        reconnect_attempt = 0
        try:
            while not self._stop_requested:
                try:
                    websocket = await websockets.connect(self._url, ping_interval=None)
                    self._websocket = websocket
                    self._is_connected = True
                    logger.info("websocket_connected", url=self._url)
                    if self._topics:
                        await self._send_operation("subscribe", self._topics)
                    if reconnect_attempt:
                        logger.info(
                            "websocket_reconnected",
                            topic_count=len(self._topics),
                        )
                    reconnect_attempt = 0
                    await self._receive_loop()
                except (ConnectionClosed, OSError, asyncio.TimeoutError) as error:
                    if self._stop_requested:
                        break
                    reconnect_attempt += 1
                    delay = min(2 ** (reconnect_attempt - 1), 30)
                    logger.warning(
                        "websocket_disconnect_detected",
                        reason=type(error).__name__,
                        reconnect_attempt=reconnect_attempt,
                        wait_seconds=delay,
                    )
                    await self._sleep_before_reconnect(delay)
                finally:
                    self._is_connected = False
                    websocket_to_close = self._websocket
                    self._websocket = None
                    if websocket_to_close is not None:
                        await websocket_to_close.close()
        finally:
            self._is_connected = False
            self._websocket = None
            self._run_task = None

    async def stop(self) -> None:
        """Request graceful shutdown and wait for any active run loop to finish."""
        self._stop_requested = True
        if self._websocket is not None:
            await self._websocket.close()
        run_task = self._run_task
        current_task = asyncio.current_task()
        if run_task is not None and run_task is not current_task:
            try:
                await asyncio.wait_for(
                    asyncio.shield(run_task), STOP_WAIT_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("websocket_stop_wait_timeout")
        logger.info("websocket_client_stopped")

    async def _receive_loop(self) -> None:
        """Receive messages, enforce heartbeat, and check subscribed-topic silence."""
        if self._websocket is None:
            raise RuntimeError("WebSocket is unavailable")
        loop = asyncio.get_running_loop()
        last_ping_at = loop.time()
        last_stale_check_at = loop.time()
        while not self._stop_requested:
            now = loop.time()
            if now - last_ping_at >= PING_INTERVAL_SECONDS:
                await self._send_raw({"op": "ping"})
                await self._await_pong()
                last_ping_at = loop.time()
                continue

            timeout = min(
                PING_INTERVAL_SECONDS - (now - last_ping_at),
                STALE_CHECK_INTERVAL_SECONDS - (now - last_stale_check_at),
            )
            raw_message = await asyncio.wait_for(
                self._websocket.recv(), timeout=timeout
            )
            await self._handle_raw_message(raw_message)

            if loop.time() - last_stale_check_at >= STALE_CHECK_INTERVAL_SECONDS:
                self._log_stale_topics()
                last_stale_check_at = loop.time()

    @staticmethod
    async def _sleep_before_reconnect(delay: float) -> None:
        """Wait for the bounded reconnect backoff without blocking the event loop."""
        await asyncio.sleep(delay)

    async def _await_pong(self) -> None:
        """Process intervening messages while waiting up to five seconds for a pong."""
        if self._websocket is None:
            raise OSError("WebSocket is unavailable")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + PONG_TIMEOUT_SECONDS
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError("pong was not received before timeout")
            raw_message = await asyncio.wait_for(
                self._websocket.recv(), timeout=remaining
            )
            if self._is_pong(raw_message):
                return
            await self._handle_raw_message(raw_message)

    async def _handle_raw_message(self, raw_message: str | bytes) -> None:
        """Parse one JSON WebSocket message and isolate malformed inputs."""
        try:
            decoded: object = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError) as error:
            logger.error(
                "websocket_json_parse_failed", exception_type=type(error).__name__
            )
            return
        if not isinstance(decoded, Mapping):
            logger.error(
                "websocket_message_invalid", message_type=type(decoded).__name__
            )
            return
        if decoded.get("op") == "pong":
            return

        topic = decoded.get("topic")
        payload = decoded.get("data")
        if not isinstance(topic, str) or not topic.startswith("kline."):
            return
        if not isinstance(payload, list):
            logger.warning("candle_normalization_failed", reason="missing data list")
            return
        for raw_kline in payload:
            await self._emit_kline(raw_kline, topic)

    async def _emit_kline(self, raw_kline: object, topic: str) -> None:
        """Normalize one update and isolate callback failures."""
        candle = self._normalize_candle(raw_kline, topic)
        if candle is None:
            return
        self._stale_detector.record_message(candle.symbol, candle.timeframe)
        logger.info(
            "candle_received",
            symbol=candle.symbol,
            interval=candle.timeframe,
            is_closed=candle.is_closed,
            close_price=str(candle.close),
        )
        try:
            await self._on_candle(candle)
        except Exception as error:
            logger.error(
                "candle_callback_error",
                exception_type=type(error).__name__,
                exception_message=str(error),
            )

    def _normalize_candle(self, raw_kline: object, topic: str) -> Candle | None:
        """Normalize a Bybit kline and enforce transport-layer integrity rules."""
        try:
            if not isinstance(raw_kline, Mapping):
                raise TypeError("kline item is not an object")
            _, interval, topic_symbol = topic.split(".", maxsplit=2)
            symbol = self._string_value(raw_kline, "symbol", default=topic_symbol)
            candle = Candle(
                symbol=symbol,
                timeframe=self._string_value(raw_kline, "interval", default=interval),
                open_time=datetime.fromtimestamp(
                    int(self._string_value(raw_kline, "start")) / 1_000,
                    tz=UTC,
                ),
                open=Decimal(self._string_value(raw_kline, "open")),
                high=Decimal(self._string_value(raw_kline, "high")),
                low=Decimal(self._string_value(raw_kline, "low")),
                close=Decimal(self._string_value(raw_kline, "close")),
                volume=Decimal(self._string_value(raw_kline, "volume")),
                turnover=Decimal(self._string_value(raw_kline, "turnover")),
                is_closed=self._boolean_value(raw_kline, "confirm"),
            )
        except (
            InvalidOperation,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as error:
            logger.warning(
                "candle_normalization_failed",
                topic=topic,
                exception_type=type(error).__name__,
            )
            return None

        failure = self._validation_failure(candle)
        if failure is None:
            return candle
        severity, event, field = failure
        getattr(logger, severity)(
            event, symbol=candle.symbol, field=field, value=str(getattr(candle, field))
        )
        return None

    @staticmethod
    def _validation_failure(candle: Candle) -> tuple[str, str, str] | None:
        """Classify integrity failures by the approved transport logging severity."""
        if candle.open <= 0:
            return "critical", "candle_price_invalid", "open"
        if candle.high < candle.open or candle.high < candle.close:
            return "critical", "candle_ohlc_violation", "high"
        if (
            candle.low > candle.open
            or candle.low > candle.close
            or candle.low > candle.high
        ):
            return "critical", "candle_ohlc_violation", "low"
        if candle.volume < 0:
            return "error", "candle_validation_failed", "volume"
        if candle.turnover < 0:
            return "error", "candle_validation_failed", "turnover"
        return None

    async def _send_operation(self, operation: str, topics: set[str]) -> None:
        """Send a subscription operation when the active connection is available."""
        if not topics:
            return
        await self._send_raw({"op": operation, "args": sorted(topics)})
        logger.info(
            "websocket_subscription_sent", operation=operation, topic_count=len(topics)
        )

    async def _send_raw(self, payload: JSONMapping) -> None:
        """Serialize and send an application-level WebSocket message."""
        if self._websocket is None:
            raise OSError("WebSocket is unavailable")
        await self._websocket.send(json.dumps(payload))

    def _log_stale_topics(self) -> None:
        """Log each stale topic, escalating BTC 4H staleness for regime safety."""
        for topic in self._stale_detector.get_stale_topics():
            _, interval, symbol = topic.split(".", maxsplit=2)
            if symbol == "BTCUSDT" and interval == "240":
                logger.error(
                    "btc_4h_topic_stale",
                    symbol=symbol,
                    interval=interval,
                    regime_data_at_risk=True,
                )
            else:
                logger.warning("stale_topic", symbol=symbol, interval=interval)

    @staticmethod
    def _topics_for(symbols: list[str], intervals: list[str]) -> set[str]:
        """Build valid public Bybit kline topic names."""
        return {
            f"kline.{interval}.{symbol}" for symbol in symbols for interval in intervals
        }

    @staticmethod
    def _is_pong(raw_message: str | bytes) -> bool:
        """Return whether a received raw message is an application-level pong."""
        try:
            decoded: object = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return False
        return isinstance(decoded, Mapping) and decoded.get("op") == "pong"

    @staticmethod
    def _string_value(
        mapping: Mapping[str, object], field: str, default: str | None = None
    ) -> str:
        """Return a required response value coerced to a string."""
        value = mapping.get(field, default)
        if value is None:
            raise KeyError(field)
        return str(value)

    @staticmethod
    def _boolean_value(mapping: Mapping[str, object], field: str) -> bool:
        """Return a required Boolean field without accepting string substitutes."""
        value = mapping.get(field)
        if not isinstance(value, bool):
            raise TypeError(field)
        return value
