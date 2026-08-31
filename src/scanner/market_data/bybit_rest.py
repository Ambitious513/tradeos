"""Read-only asynchronous client for Bybit V5 public market-data endpoints."""

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import TypeAlias

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type
from tenacity.wait import wait_exponential

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.models import SymbolInfo, Ticker24H
from scanner.models import Candle

TESTNET_BASE_URL = "https://api-testnet.bybit.com"
MAINNET_BASE_URL = "https://api.bybit.com"
KLINE_ENDPOINT = "/v5/market/kline"
INSTRUMENTS_ENDPOINT = "/v5/market/instruments-info"
TICKERS_ENDPOINT = "/v5/market/tickers"
SERVER_TIME_ENDPOINT = "/v5/market/time"

logger = get_logger("market_data.rest")

JSONMapping: TypeAlias = Mapping[str, object]


class BybitAPIError(Exception):
    """A public Bybit API request failed or returned an invalid payload."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        endpoint: str | None = None,
        ret_code: int | None = None,
    ) -> None:
        """Initialize the error with response metadata suitable for diagnostics."""
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.ret_code = ret_code


class _RetryableHTTPError(Exception):
    """An HTTP 5xx response that tenacity may retry."""

    def __init__(self, status_code: int, endpoint: str) -> None:
        super().__init__(f"Bybit server error {status_code} at {endpoint}")
        self.status_code = status_code
        self.endpoint = endpoint


class _RateLimitError(Exception):
    """A rate-limit response that supplies its requested retry delay."""

    def __init__(self, endpoint: str, retry_after_seconds: float) -> None:
        super().__init__(f"Bybit rate limit at {endpoint}")
        self.endpoint = endpoint
        self.retry_after_seconds = retry_after_seconds


class _EndpointRateLimiter:
    """Serialize endpoint requests to conservatively respect Bybit public limits."""

    _intervals: dict[str, float] = {
        KLINE_ENDPOINT: 0.5,
        INSTRUMENTS_ENDPOINT: 6.0,
        TICKERS_ENDPOINT: 0.5,
        SERVER_TIME_ENDPOINT: 0.5,
    }

    def __init__(self) -> None:
        """Initialize endpoint locks and next-allowed request timestamps."""
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_allowed_at: dict[str, float] = {}

    async def wait(self, endpoint: str) -> None:
        """Wait until a request is permitted for the requested endpoint."""
        lock = self._locks.setdefault(endpoint, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            allowed_at = self._next_allowed_at.get(endpoint, now)
            if allowed_at > now:
                await asyncio.sleep(allowed_at - now)
            self._next_allowed_at[endpoint] = loop.time() + self._intervals.get(
                endpoint, 0.5
            )


class BybitRESTClient:
    """Fetch public Bybit V5 market data without trading or account access.

    Source: docs/DATA_CONTRACT.md sections 2, 3, 5, 8, and 10.
    """

    def __init__(self, config: ScannerConfig) -> None:
        """Create a public REST client, enforcing testnet safety by default."""
        if not config.bybit_testnet and config.environment != "live":
            raise RuntimeError(
                "bybit_testnet=False requires environment='live'. "
                "This is a safety guard against accidental mainnet connections."
            )

        self._base_url = TESTNET_BASE_URL if config.bybit_testnet else MAINNET_BASE_URL
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        self._rate_limiter = _EndpointRateLimiter()
        self._retry_wait: Callable[[RetryCallState], float] = self._wait_for_retry
        logger.info("rest_client_initialized", base_url=self._base_url)

    @property
    def base_url(self) -> str:
        """Return the selected public API base URL for observability and tests."""
        return self._base_url

    async def __aenter__(self) -> "BybitRESTClient":
        """Enter the client context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client on context exit."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()
        logger.info("rest_client_closed")

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
        end_time_ms: int | None = None,
    ) -> list[Candle]:
        """Fetch validated, closed candles ordered from oldest to newest."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        params: dict[str, str | int] = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if end_time_ms is not None:
            params["end"] = end_time_ms

        payload = await self._get_json(KLINE_ENDPOINT, params=params, symbol=symbol)
        rows = self._result_rows(payload, KLINE_ENDPOINT)
        if not rows:
            logger.warning("empty_response", symbol=symbol, endpoint=KLINE_ENDPOINT)
            return []

        candles: list[Candle] = []
        for row in rows:
            candle = self._normalize_candle(row, symbol, interval)
            if candle is not None:
                candles.append(candle)
        return sorted(candles, key=lambda candle: candle.open_time)

    async def get_instruments_info(self, symbol: str | None = None) -> list[SymbolInfo]:
        """Fetch public USDT linear-perpetual instrument metadata."""
        params: dict[str, str] = {"category": "linear"}
        if symbol is not None:
            params["symbol"] = symbol

        payload = await self._get_json(
            INSTRUMENTS_ENDPOINT, params=params, symbol=symbol
        )
        rows = self._result_rows(payload, INSTRUMENTS_ENDPOINT)
        if not rows:
            logger.warning(
                "empty_response", symbol=symbol, endpoint=INSTRUMENTS_ENDPOINT
            )
            return []

        instruments: list[SymbolInfo] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                logger.warning("instrument_normalization_failed", symbol=symbol)
                continue
            row = raw_row
            try:
                price_filter = self._mapping_value(row, "priceFilter")
                lot_size_filter = self._mapping_value(row, "lotSizeFilter")
                leverage_filter = self._mapping_value(row, "leverageFilter")
                instruments.append(
                    SymbolInfo(
                        symbol=self._string_value(row, "symbol"),
                        base_coin=self._string_value(row, "baseCoin"),
                        quote_coin=self._string_value(row, "quoteCoin"),
                        status=self._string_value(row, "status"),
                        tick_size=Decimal(self._string_value(price_filter, "tickSize")),
                        lot_size=Decimal(
                            self._string_value(lot_size_filter, "qtyStep")
                        ),
                        min_order_qty=Decimal(
                            self._string_value(lot_size_filter, "minOrderQty")
                        ),
                        max_leverage=float(
                            self._string_value(leverage_filter, "maxLeverage")
                        ),
                        contract_type=self._string_value(row, "contractType"),
                    )
                )
            except (InvalidOperation, KeyError, TypeError, ValueError) as error:
                logger.warning(
                    "instrument_normalization_failed",
                    symbol=symbol,
                    exception_type=type(error).__name__,
                )
        return instruments

    async def get_tickers_24h(self, symbol: str | None = None) -> list[Ticker24H]:
        """Fetch public 24-hour ticker values for linear perpetual instruments."""
        params: dict[str, str] = {"category": "linear"}
        if symbol is not None:
            params["symbol"] = symbol

        payload = await self._get_json(TICKERS_ENDPOINT, params=params, symbol=symbol)
        rows = self._result_rows(payload, TICKERS_ENDPOINT)
        if not rows:
            logger.warning("empty_response", symbol=symbol, endpoint=TICKERS_ENDPOINT)
            return []

        timestamp = self._payload_timestamp(payload)
        tickers: list[Ticker24H] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                logger.warning("ticker_normalization_failed", symbol=symbol)
                continue
            row = raw_row
            try:
                tickers.append(
                    Ticker24H(
                        symbol=self._string_value(row, "symbol"),
                        last_price=Decimal(self._string_value(row, "lastPrice")),
                        high_24h=Decimal(self._string_value(row, "highPrice24h")),
                        low_24h=Decimal(self._string_value(row, "lowPrice24h")),
                        volume_24h=Decimal(self._string_value(row, "volume24h")),
                        turnover_24h=Decimal(self._string_value(row, "turnover24h")),
                        price_change_pct_24h=float(
                            self._string_value(row, "price24hPcnt")
                        )
                        * 100,
                        timestamp=timestamp,
                    )
                )
            except (InvalidOperation, KeyError, TypeError, ValueError) as error:
                logger.warning(
                    "ticker_normalization_failed",
                    symbol=symbol,
                    exception_type=type(error).__name__,
                )
        return tickers

    async def get_server_time(self) -> int:
        """Fetch Bybit's current UTC server time in milliseconds."""
        payload = await self._get_json(SERVER_TIME_ENDPOINT, params={}, symbol=None)
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise BybitAPIError("missing time result", endpoint=SERVER_TIME_ENDPOINT)
        try:
            if "timeNano" in result:
                return int(self._string_value(result, "timeNano")) // 1_000_000
            return int(self._string_value(result, "timeSecond")) * 1_000
        except (KeyError, TypeError, ValueError) as error:
            logger.error(
                "server_time_parse_failed",
                endpoint=SERVER_TIME_ENDPOINT,
                exception_type=type(error).__name__,
            )
            raise BybitAPIError(
                "invalid server time response", endpoint=SERVER_TIME_ENDPOINT
            ) from error

    async def _get_json(
        self,
        endpoint: str,
        params: Mapping[str, str | int],
        symbol: str | None,
    ) -> JSONMapping:
        """Perform a rate-limited public GET with the approved retry policy."""
        started_at = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=lambda state: state.attempt_number >= 3,
                wait=self._retry_wait,
                retry=retry_if_exception_type(
                    (
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        _RetryableHTTPError,
                        _RateLimitError,
                    )
                ),
                before_sleep=self._log_retry,
                reraise=True,
            ):
                with attempt:
                    payload = await self._request_once(endpoint, params)
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            _RetryableHTTPError,
            _RateLimitError,
        ) as error:
            logger.error(
                "retry_exhausted",
                endpoint=endpoint,
                symbol=symbol,
                exception_type=type(error).__name__,
            )
            raise BybitAPIError(
                "Bybit request failed after retries", endpoint=endpoint
            ) from error

        latency_ms = round((time.perf_counter() - started_at) * 1_000, 2)
        logger.info(
            "fetch_succeeded",
            endpoint=endpoint,
            symbol=symbol,
            latency_ms=latency_ms,
        )
        return payload

    async def _request_once(
        self, endpoint: str, params: Mapping[str, str | int]
    ) -> JSONMapping:
        """Issue one HTTP request and classify its response for retry handling."""
        await self._rate_limiter.wait(endpoint)
        response = await self._client.get(endpoint, params=params)
        if response.status_code == 429:
            retry_after_seconds = self._retry_after_seconds(response)
            logger.warning(
                "rate_limit_received",
                endpoint=endpoint,
                wait_seconds=retry_after_seconds,
            )
            raise _RateLimitError(endpoint, retry_after_seconds)
        if response.status_code >= 500:
            raise _RetryableHTTPError(response.status_code, endpoint)
        if response.status_code >= 400:
            logger.error(
                "non_retryable_http_error",
                status_code=response.status_code,
                endpoint=endpoint,
                body_excerpt=response.text[:500],
            )
            raise BybitAPIError(
                "non-retryable Bybit HTTP error",
                status_code=response.status_code,
                endpoint=endpoint,
            )

        try:
            raw_payload: object = response.json()
        except ValueError as error:
            logger.error("json_parse_failure", endpoint=endpoint)
            raise BybitAPIError("invalid JSON response", endpoint=endpoint) from error
        if not isinstance(raw_payload, Mapping):
            logger.error("json_parse_failure", endpoint=endpoint)
            raise BybitAPIError("JSON response is not an object", endpoint=endpoint)

        ret_code_value = raw_payload.get("retCode", 0)
        try:
            ret_code = int(str(ret_code_value))
        except ValueError as error:
            logger.error("json_parse_failure", endpoint=endpoint)
            raise BybitAPIError("invalid retCode", endpoint=endpoint) from error
        if ret_code != 0:
            ret_msg = str(raw_payload.get("retMsg", "Bybit API error"))
            logger.error("bybit_api_error", endpoint=endpoint, ret_code=ret_code)
            raise BybitAPIError(ret_msg, endpoint=endpoint, ret_code=ret_code)
        return raw_payload

    def _wait_for_retry(self, retry_state: RetryCallState) -> float:
        """Use Retry-After for 429s and bounded exponential delays otherwise."""
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, _RateLimitError):
            return exception.retry_after_seconds
        return wait_exponential(multiplier=1, min=1, max=10)(retry_state)

    def _log_retry(self, retry_state: RetryCallState) -> None:
        """Log each approved retry without including credentials or response secrets."""
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "request_retrying",
            attempt_number=retry_state.attempt_number,
            exception_type=type(exception).__name__,
            wait_seconds=(
                retry_state.next_action.sleep if retry_state.next_action else None
            ),
        )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        """Parse a safe retry delay from the response, defaulting to five seconds."""
        try:
            return max(float(response.headers.get("Retry-After", "5")), 0.0)
        except ValueError:
            return 5.0

    def _normalize_candle(
        self, row: object, symbol: str, interval: str
    ) -> Candle | None:
        """Normalize and validate one Bybit kline row, discarding invalid data."""
        try:
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("row must contain seven kline values")
            candle = Candle(
                symbol=symbol,
                timeframe=interval,
                open_time=datetime.fromtimestamp(int(str(row[0])) / 1_000, tz=UTC),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
                turnover=Decimal(str(row[6])),
                is_closed=True,
            )
        except (InvalidOperation, TypeError, ValueError, OverflowError) as error:
            logger.warning(
                "candle_normalization_failed",
                symbol=symbol,
                exception_type=type(error).__name__,
            )
            return None

        invalid_field = self._invalid_candle_field(candle)
        if invalid_field is not None:
            log_method = (
                logger.critical
                if invalid_field in {"open", "high", "low"}
                else logger.error
            )
            log_method(
                "candle_validation_failed",
                symbol=symbol,
                field=invalid_field,
                value=str(getattr(candle, invalid_field)),
            )
            return None
        return candle

    @staticmethod
    def _invalid_candle_field(candle: Candle) -> str | None:
        """Return the first DATA_CONTRACT validation failure, if any."""
        if not candle.is_closed:
            return "is_closed"
        if candle.open <= 0:
            return "open"
        if candle.high < candle.open or candle.high < candle.close:
            return "high"
        if (
            candle.low > candle.open
            or candle.low > candle.close
            or candle.low > candle.high
        ):
            return "low"
        if candle.volume < 0:
            return "volume"
        if candle.turnover < 0:
            return "turnover"
        return None

    @staticmethod
    def _result_rows(payload: JSONMapping, endpoint: str) -> list[object]:
        """Extract a Bybit result list, raising on malformed response structure."""
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise BybitAPIError("missing result object", endpoint=endpoint)
        rows = result.get("list")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise BybitAPIError("result list is invalid", endpoint=endpoint)
        return rows

    @staticmethod
    def _mapping_value(mapping: JSONMapping, field: str) -> JSONMapping:
        """Return a nested JSON object or raise a descriptive key error."""
        value = mapping.get(field)
        if not isinstance(value, Mapping):
            raise KeyError(field)
        return value

    @staticmethod
    def _string_value(mapping: JSONMapping, field: str) -> str:
        """Return a required string-like response field."""
        value = mapping.get(field)
        if value is None:
            raise KeyError(field)
        return str(value)

    @staticmethod
    def _payload_timestamp(payload: JSONMapping) -> datetime:
        """Return the response timestamp or a UTC fallback for public ticker data."""
        raw_timestamp = payload.get("time")
        try:
            return datetime.fromtimestamp(int(str(raw_timestamp)) / 1_000, tz=UTC)
        except (TypeError, ValueError, OverflowError):
            return datetime.now(UTC)
