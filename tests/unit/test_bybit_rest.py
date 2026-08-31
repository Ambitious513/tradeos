"""Mocked unit tests for the read-only Bybit V5 REST client."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from scanner.config import ScannerConfig
from scanner.market_data.bybit_rest import (
    INSTRUMENTS_ENDPOINT,
    KLINE_ENDPOINT,
    MAINNET_BASE_URL,
    TESTNET_BASE_URL,
    TICKERS_ENDPOINT,
    BybitAPIError,
    BybitRESTClient,
)

FIXTURES_DIRECTORY = Path(__file__).parents[1] / "fixtures"


def fixture_payload(name: str) -> dict[str, object]:
    """Load one synthetic Bybit API response fixture."""
    return json.loads((FIXTURES_DIRECTORY / name).read_text(encoding="utf-8"))


def test_client_init_testnet_default() -> None:
    """Default settings instantiate a testnet-only REST client."""
    client = BybitRESTClient(ScannerConfig(_env_file=None))
    assert client.base_url == TESTNET_BASE_URL


def test_uses_testnet_url() -> None:
    """An explicit testnet setting cannot select the mainnet URL."""
    client = BybitRESTClient(ScannerConfig(_env_file=None, bybit_testnet=True))
    assert client.base_url == TESTNET_BASE_URL
    assert MAINNET_BASE_URL not in client.base_url


def test_mainnet_blocked_in_dev() -> None:
    """Development cannot silently connect to Bybit mainnet."""
    with pytest.raises(RuntimeError, match="requires environment='live'"):
        BybitRESTClient(
            ScannerConfig(_env_file=None, bybit_testnet=False, environment="development")
        )


def test_mainnet_allowed_in_live_env() -> None:
    """The explicit live configuration is the only mainnet opt-in path."""
    client = BybitRESTClient(
        ScannerConfig(_env_file=None, bybit_testnet=False, environment="live")
    )
    assert client.base_url == MAINNET_BASE_URL


@pytest.mark.asyncio
async def test_get_klines_parses_correctly() -> None:
    """Kline rows normalize into the stable Candle model."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60", limit=2)
    assert len(candles) == 2
    assert candles[0].symbol == "SOLUSDT"
    assert candles[0].timeframe == "60"


@pytest.mark.asyncio
async def test_get_klines_decimal_precision() -> None:
    """Prices are retained as Decimal values without float conversion."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60")
    assert str(candles[0].open) == "150.00000001"


@pytest.mark.asyncio
async def test_candles_always_closed() -> None:
    """REST candles are normalized as confirmed, strategy-safe candles."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60")
    assert all(candle.is_closed for candle in candles)


@pytest.mark.asyncio
async def test_candles_sorted_ascending() -> None:
    """Bybit's reverse-ordered rows are returned in chronological order."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60")
    assert candles[0].open_time < candles[1].open_time


@pytest.mark.asyncio
async def test_invalid_candle_ohlc_violation_discarded() -> None:
    """An invalid high/low row is discarded and reported at ERROR level."""
    payload = fixture_payload("bybit_candles_response.json")
    rows = payload["result"]["list"]  # type: ignore[index]
    rows.append(["1788120000000", "100", "90", "95", "99", "1", "100"])  # type: ignore[union-attr]
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with capture_logs() as logs, respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60")
    assert len(candles) == 2
    assert any(
        log["event"] == "candle_validation_failed" and log["log_level"] == "error"
        for log in logs
    )


@pytest.mark.asyncio
async def test_invalid_candle_logs_error() -> None:
    """AC-021: every discarded invalid candle emits an ERROR-level event."""
    payload = fixture_payload("bybit_candles_response.json")
    rows = payload["result"]["list"]  # type: ignore[index]
    rows.append(["1788120000000", "0", "1", "0", "1", "1", "1"])  # type: ignore[union-attr]
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with capture_logs() as logs, respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            await client.get_klines("SOLUSDT", "60")
    validation_logs = [
        log for log in logs if log["event"] == "candle_validation_failed"
    ]
    assert validation_logs
    assert all(log["log_level"] == "error" for log in validation_logs)


@pytest.mark.asyncio
async def test_invalid_candle_zero_price_discarded() -> None:
    """A zero-price candle never enters the normalized output."""
    payload = fixture_payload("bybit_candles_response.json")
    rows = payload["result"]["list"]  # type: ignore[index]
    rows.append(["1788120000000", "0", "1", "0", "1", "1", "1"])  # type: ignore[union-attr]
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            candles = await client.get_klines("SOLUSDT", "60")
    assert len(candles) == 2


@pytest.mark.asyncio
async def test_empty_klines_response() -> None:
    """An empty Bybit list returns an empty result safely."""
    payload = {"retCode": 0, "retMsg": "OK", "result": {"list": []}}
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            assert await client.get_klines("SOLUSDT", "60") == []


@pytest.mark.asyncio
async def test_get_instruments_info_parses() -> None:
    """Instrument metadata maps to the public SymbolInfo data contract."""
    payload = fixture_payload("bybit_instruments_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{INSTRUMENTS_ENDPOINT}").respond(200, json=payload)
            instruments = await client.get_instruments_info("SOLUSDT")
    assert instruments[0].tick_size.as_tuple().exponent == -3
    assert instruments[0].contract_type == "LinearPerpetual"


@pytest.mark.asyncio
async def test_get_tickers_24h_parses() -> None:
    """Ticker data maps to the public Ticker24H data contract."""
    payload = fixture_payload("bybit_tickers_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{TICKERS_ENDPOINT}").respond(200, json=payload)
            tickers = await client.get_tickers_24h("SOLUSDT")
    assert tickers[0].price_change_pct_24h == 5.5
    assert str(tickers[0].turnover_24h) == "30456789.1234"


@pytest.mark.asyncio
async def test_rate_limit_retry_waits_and_succeeds() -> None:
    """A mocked 429 honors Retry-After and succeeds on its second attempt."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            route = mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}")
            route.side_effect = [
                httpx.Response(429, headers={"Retry-After": "0"}),
                httpx.Response(200, json=payload),
            ]
            candles = await client.get_klines("SOLUSDT", "60")
    assert len(candles) == 2
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_server_error_retries_three_times() -> None:
    """A temporary server failure is retried until a success response arrives."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        client._retry_wait = lambda _: 0.0
        with respx.mock() as mock:
            route = mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}")
            route.side_effect = [
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json=payload),
            ]
            assert len(await client.get_klines("SOLUSDT", "60")) == 2
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises_bybit_api_error() -> None:
    """Three exhausted server-error attempts surface the public API exception."""
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        client._retry_wait = lambda _: 0.0
        with respx.mock() as mock:
            route = mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(500)
            with pytest.raises(BybitAPIError, match="after retries"):
                await client.get_klines("SOLUSDT", "60")
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_400_raises_immediately_no_retry() -> None:
    """Bad requests are logged and surfaced without an unsafe retry."""
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            route = mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(400, text="bad")
            with pytest.raises(BybitAPIError) as error:
                await client.get_klines("SOLUSDT", "60")
    assert error.value.status_code == 400
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_json_parse_error_raises() -> None:
    """Malformed JSON is never silently treated as valid market data."""
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, content=b"not json")
            with pytest.raises(BybitAPIError, match="invalid JSON"):
                await client.get_klines("SOLUSDT", "60")


@pytest.mark.asyncio
async def test_context_manager_closes_client() -> None:
    """The async context manager releases HTTP resources on exit."""
    client = BybitRESTClient(ScannerConfig(_env_file=None))
    async with client:
        assert client._client.is_closed is False
    assert client._client.is_closed is True


@pytest.mark.asyncio
async def test_structured_log_on_success() -> None:
    """Successful fetches emit a structured success event."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        with capture_logs() as logs, respx.mock() as mock:
            mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}").respond(200, json=payload)
            await client.get_klines("SOLUSDT", "60")
    assert any(log["event"] == "fetch_succeeded" for log in logs)


@pytest.mark.asyncio
async def test_structured_log_on_retry() -> None:
    """Retry attempts emit a structured warning event."""
    payload = fixture_payload("bybit_candles_response.json")
    async with BybitRESTClient(ScannerConfig(_env_file=None)) as client:
        client._retry_wait = lambda _: 0.0
        with capture_logs() as logs, respx.mock() as mock:
            route = mock.get(f"{TESTNET_BASE_URL}{KLINE_ENDPOINT}")
            route.side_effect = [httpx.Response(500), httpx.Response(200, json=payload)]
            await client.get_klines("SOLUSDT", "60")
    assert any(log["event"] == "request_retrying" for log in logs)
