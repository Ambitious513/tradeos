"""Maintain closed-candle buffers fed by Bybit REST and WebSocket transports."""

from collections.abc import Iterable
from datetime import UTC

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.bybit_rest import BybitAPIError, BybitRESTClient
from scanner.market_data.bybit_ws import BybitWebSocketClient
from scanner.models import Candle

INTERVAL_TO_MS: dict[str, int] = {"60": 3_600_000, "240": 14_400_000}

logger = get_logger("candle_store")

_CandleKey = tuple[str, str]


class CandleStore:
    """Keep bounded, strategy-safe candle histories for subscribed symbols."""

    def __init__(
        self,
        rest_client: BybitRESTClient,
        ws_client: BybitWebSocketClient,
        config: ScannerConfig,
        buffer_size: int = 200,
    ) -> None:
        """Create an empty in-memory store backed by existing transport clients."""
        if buffer_size < 1:
            raise ValueError("buffer_size must be at least 1")
        self._rest_client = rest_client
        self._ws_client = ws_client
        self._config = config
        self._buffer_size = buffer_size
        self._closed_buffers: dict[_CandleKey, list[Candle]] = {}
        self._forming_candles: dict[_CandleKey, Candle] = {}
        self._subscribed_symbols: frozenset[str] = frozenset()

    @property
    def subscribed_symbols(self) -> frozenset[str]:
        """Return the symbols successfully requested from the WebSocket client."""
        return self._subscribed_symbols

    async def initialize(self, symbols: list[str], intervals: list[str]) -> None:
        """Pre-fill closed history, then subscribe to live candle updates."""
        for symbol in symbols:
            for interval in intervals:
                try:
                    candles = await self._rest_client.get_klines(
                        symbol, interval, limit=self._buffer_size
                    )
                except BybitAPIError as error:
                    self._log_prefill_failure(symbol, interval, error)
                    continue

                key = (symbol, interval)
                for candle in sorted(candles, key=lambda item: item.open_time):
                    if candle.is_closed:
                        self._insert_closed(key, candle)
                logger.info(
                    "candle_buffer_prefilled",
                    symbol=symbol,
                    interval=interval,
                    count=len(self._closed_buffers.get(key, [])),
                )

        await self._ws_client.subscribe(symbols, intervals)
        self._subscribed_symbols = frozenset(symbols)
        logger.info(
            "candle_store_initialized",
            symbol_count=len(symbols),
            interval_count=len(intervals),
        )

    async def run_forever(self) -> None:
        """Delegate streaming to the configured WebSocket transport."""
        await self._ws_client.run_forever()

    async def stop(self) -> None:
        """Gracefully stop the configured WebSocket transport."""
        await self._ws_client.stop()

    async def on_candle(self, candle: Candle) -> None:
        """Store a confirmed live candle and fill any detected history gap."""
        key = (candle.symbol, candle.timeframe)
        if not candle.is_closed:
            self._forming_candles[key] = candle
            return

        buffer = self._closed_buffers.setdefault(key, [])
        if any(existing.open_time == candle.open_time for existing in buffer):
            return

        latest = buffer[-1] if buffer else None
        if latest is not None and candle.open_time > latest.open_time:
            await self._fill_gap_if_needed(key, latest, candle)

        self._insert_closed(key, candle)
        logger.info(
            "candle_closed_stored",
            symbol=candle.symbol,
            interval=candle.timeframe,
            open_time=candle.open_time.isoformat(),
        )

    def get_closed_candles(self, symbol: str, interval: str, n: int) -> list[Candle]:
        """Return up to ``n`` newest confirmed candles in oldest-first order."""
        if n <= 0:
            return []
        buffer = self._closed_buffers.get((symbol, interval), [])
        closed_candles = [candle for candle in buffer if candle.is_closed]
        if len(closed_candles) != len(buffer):
            logger.error("forming_candle_in_buffer", symbol=symbol, interval=interval)
        return closed_candles[-n:]

    def get_forming_candle(self, symbol: str, interval: str) -> Candle | None:
        """Return the newest forming candle for future display-only consumers."""
        return self._forming_candles.get((symbol, interval))

    def is_ready(self, symbol: str, interval: str, min_candles: int) -> bool:
        """Return whether the requested history contains enough closed candles."""
        return (
            len(self.get_closed_candles(symbol, interval, min_candles)) >= min_candles
        )

    async def _fill_gap_if_needed(
        self, key: _CandleKey, latest: Candle, new_candle: Candle
    ) -> None:
        """Fetch missing closed candles before adding a later live update."""
        interval_ms = INTERVAL_TO_MS.get(new_candle.timeframe)
        if interval_ms is None:
            return

        elapsed_ms = int(
            (new_candle.open_time - latest.open_time).total_seconds() * 1_000
        )
        if elapsed_ms <= interval_ms:
            return

        gap_candles = (elapsed_ms // interval_ms) - 1
        logger.warning(
            "candle_gap_detected",
            symbol=new_candle.symbol,
            interval=new_candle.timeframe,
            gap_candles=gap_candles,
        )
        end_time_ms = int(new_candle.open_time.astimezone(UTC).timestamp() * 1_000) - 1
        try:
            filled_candles = await self._rest_client.get_klines(
                new_candle.symbol,
                new_candle.timeframe,
                limit=min(gap_candles + 5, 200),
                end_time_ms=end_time_ms,
            )
        except BybitAPIError as error:
            logger.error(
                "gap_fill_failed",
                symbol=new_candle.symbol,
                interval=new_candle.timeframe,
                exception_type=type(error).__name__,
            )
            return

        inserted_count = self._insert_gap_fill(key, filled_candles)
        logger.info(
            "candle_gap_filled",
            symbol=new_candle.symbol,
            interval=new_candle.timeframe,
            filled_count=inserted_count,
        )

    def _insert_gap_fill(self, key: _CandleKey, candles: Iterable[Candle]) -> int:
        """Insert unique confirmed REST candles and report how many were retained."""
        existing_open_times = {
            candle.open_time for candle in self._closed_buffers.get(key, [])
        }
        inserted_count = 0
        for candle in sorted(candles, key=lambda item: item.open_time):
            if candle.is_closed and candle.open_time not in existing_open_times:
                self._insert_closed(key, candle)
                existing_open_times.add(candle.open_time)
                inserted_count += 1
        return inserted_count

    def _insert_closed(self, key: _CandleKey, candle: Candle) -> None:
        """Insert one confirmed candle in time order and evict the oldest excess."""
        buffer = self._closed_buffers.setdefault(key, [])
        if any(existing.open_time == candle.open_time for existing in buffer):
            return
        buffer.append(candle)
        buffer.sort(key=lambda item: item.open_time)
        del buffer[: max(0, len(buffer) - self._buffer_size)]

    def _log_prefill_failure(
        self, symbol: str, interval: str, error: BybitAPIError
    ) -> None:
        """Log BTC pre-fill failures as errors and other symbols as warnings."""
        fields = {
            "symbol": symbol,
            "interval": interval,
            "exception_type": type(error).__name__,
        }
        if symbol == "BTCUSDT":
            logger.error("btc_prefill_failed", **fields)
            return
        logger.warning("prefill_failed", **fields)
