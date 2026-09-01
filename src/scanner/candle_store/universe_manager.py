"""Refresh and cache the scanner's Bybit symbol universe.

Two independent tracks are merged on each refresh:

* **Volume track** — USDT perpetuals with 24H turnover >= ``universe_min_volume_usd``.
  Covers established, liquid coins.

* **New-listing track** — USDT perpetuals whose ``launchTime`` falls within the
  last ``universe_new_listing_days`` days, regardless of turnover.  New listings
  often produce the extreme RSI / EMA-extension events the strategy targets.

BTCUSDT is always included for regime detection.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.bybit_rest import BybitAPIError, BybitRESTClient

logger = get_logger("universe_manager")


class UniverseRefreshError(Exception):
    """Universe fetch failed and no cached universe is available."""


class UniverseManager:
    """Maintain a cached, dual-track list of USDT perpetual symbols."""

    def __init__(
        self,
        rest_client: BybitRESTClient,
        config: ScannerConfig,
        excluded_symbols: frozenset[str] | None = None,
    ) -> None:
        """Create a universe manager with an initially empty symbol cache."""
        self._rest_client = rest_client
        self._minimum_turnover = Decimal(str(config.universe_min_volume_usd))
        self._new_listing_days = config.universe_new_listing_days
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
        """Fetch, filter, sort, and cache the currently eligible symbols.

        Merges two tracks:
        - Volume track: 24H turnover >= minimum_turnover
        - New-listing track: launchTime within last new_listing_days days
        """
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

        # --- Volume track ---
        volume_qualified = {
            ticker.symbol
            for ticker in tickers
            if ticker.symbol.endswith("USDT")
            and ticker.symbol not in self._excluded_symbols
            and ticker.turnover_24h >= self._minimum_turnover
        }

        # --- New-listing track ---
        new_listing_qualified: set[str] = set()
        try:
            instruments = await self._rest_client.get_instruments_info()
            cutoff = datetime.now(UTC) - timedelta(days=self._new_listing_days)
            new_listing_qualified = {
                info.symbol
                for info in instruments
                if info.symbol.endswith("USDT")
                and info.symbol not in self._excluded_symbols
                and info.status == "Trading"
                and info.launch_time is not None
                and info.launch_time >= cutoff
            }
            if new_listing_qualified:
                logger.info(
                    "new_listings_detected",
                    count=len(new_listing_qualified),
                    symbols=sorted(new_listing_qualified),
                    window_days=self._new_listing_days,
                )
        except BybitAPIError as error:
            logger.warning(
                "new_listing_fetch_failed",
                reason=type(error).__name__,
            )

        qualified_symbols = volume_qualified | new_listing_qualified
        qualified_symbols.add("BTCUSDT")
        self._symbols = sorted(qualified_symbols)
        self._last_refreshed_at = datetime.now(UTC)
        logger.info(
            "universe_refreshed",
            total=len(self._symbols),
            volume_track=len(volume_qualified),
            new_listing_track=len(new_listing_qualified),
        )
        return self.symbols
