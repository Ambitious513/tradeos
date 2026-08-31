"""Refresh and cache the scanner's Bybit symbol universe."""

from datetime import UTC, datetime
from decimal import Decimal

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.bybit_rest import BybitAPIError, BybitRESTClient

logger = get_logger("universe_manager")


class UniverseRefreshError(Exception):
    """Universe fetch failed and no cached universe is available."""


class UniverseManager:
    """Maintain a cached, volume-qualified list of USDT perpetual symbols."""

    def __init__(
        self,
        rest_client: BybitRESTClient,
        config: ScannerConfig,
        excluded_symbols: frozenset[str] | None = None,
    ) -> None:
        """Create a universe manager with an initially empty symbol cache."""
        self._rest_client = rest_client
        self._minimum_turnover = Decimal(str(config.universe_min_volume_usd))
        self._excluded_symbols = excluded_symbols or frozenset()
        self._symbols: list[str] = []
        self._last_refreshed_at: datetime | None = None

    @property
    def symbols(self) -> list[str]:
        """Return a copy of the most recently successfully refreshed universe."""
        return list(self._symbols)

    @property
    def last_refreshed_at(self) -> datetime | None:
        """Return the UTC time of the most recent successful refresh."""
        return self._last_refreshed_at

    async def refresh(self) -> list[str]:
        """Fetch, filter, sort, and cache the currently eligible symbols."""
        try:
            tickers = await self._rest_client.get_tickers_24h()
        except BybitAPIError as error:
            if self._symbols:
                logger.warning(
                    "universe_refresh_used_cache", reason=type(error).__name__
                )
                return self.symbols
            logger.error(
                "universe_refresh_failed_no_cache",
                exception_type=type(error).__name__,
            )
            raise UniverseRefreshError("unable to fetch the symbol universe") from error

        qualified_symbols = {
            ticker.symbol
            for ticker in tickers
            if ticker.symbol.endswith("USDT")
            and ticker.symbol not in self._excluded_symbols
            and ticker.turnover_24h >= self._minimum_turnover
        }
        qualified_symbols.add("BTCUSDT")
        self._symbols = sorted(qualified_symbols)
        self._last_refreshed_at = datetime.now(UTC)
        return self.symbols
