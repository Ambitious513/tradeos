"""On-demand classification of the BTC 4H market regime."""

from datetime import UTC, datetime
from decimal import Decimal

from scanner.candle_store.candle_store import CandleStore
from scanner.config import ScannerConfig
from scanner.indicators import ema
from scanner.logging_setup import get_logger
from scanner.models import Regime

logger = get_logger("regime.detector")


class RegimeDetector:
    """Classify the current BTC 4H market regime for the A+ Scanner."""

    BTC_SYMBOL = "BTCUSDT"
    PRIMARY_INTERVAL = "240"
    MIN_CANDLES = 200

    def __init__(self, candle_store: CandleStore, config: ScannerConfig) -> None:
        """Create a detector backed by the current in-memory candle store."""
        self._candle_store = candle_store
        self._neutral_threshold = Decimal(str(config.btc_neutral_threshold_pct))
        self._pump_threshold = Decimal(str(config.pump_threshold_pct))
        self._dump_threshold = Decimal(str(config.dump_threshold_pct))
        self._last_regime = Regime.UNDEFINED
        self._last_classified_at: datetime | None = None

    @property
    def last_regime(self) -> Regime:
        """Return the result of the most recent classification."""
        return self._last_regime

    @property
    def last_classified_at(self) -> datetime | None:
        """Return the UTC timestamp of the most recent classification."""
        return self._last_classified_at

    def classify(self) -> Regime:
        """Classify BTC from fresh closed 4H candles without TTL caching.

        Source: tasks/active/TASK_007_REGIME_DETECTOR.md R-002.
        """
        candles = self._candle_store.get_closed_candles(
            self.BTC_SYMBOL, self.PRIMARY_INTERVAL, self.MIN_CANDLES
        )
        if len(candles) < self.MIN_CANDLES:
            logger.info(
                "regime_undefined_insufficient_data",
                candle_count=len(candles),
                required=self.MIN_CANDLES,
            )
            return self._record_classification(Regime.UNDEFINED)

        close_now = candles[-1].close
        close_24h_ago = candles[-7].close
        if close_24h_ago == 0:
            logger.info("regime_undefined_invalid_change", reference_close="0")
            return self._record_classification(Regime.UNDEFINED)
        change_pct = (close_now - close_24h_ago) / close_24h_ago * Decimal(100)

        if abs(change_pct) <= self._neutral_threshold:
            return self._record_classification(Regime.NEUTRAL, change_pct=change_pct)

        ema7 = ema(candles, period=7)
        ema14 = ema(candles, period=14)
        ema28 = ema(candles, period=28)
        ema200 = ema(candles, period=200)
        ema_values = (ema7, ema14, ema28, ema200)
        if ema7 is None or ema14 is None or ema28 is None or ema200 is None:
            return self._record_classification(
                Regime.UNDEFINED, change_pct=change_pct, ema_values=ema_values
            )

        if change_pct >= self._pump_threshold or change_pct <= -self._dump_threshold:
            logger.info("regime_undefined_pump_detected", change_pct=str(change_pct))
            return self._record_classification(
                Regime.UNDEFINED, change_pct=change_pct, ema_values=ema_values
            )

        bullish_stack = ema7 > ema14 > ema28 > ema200
        bearish_stack = ema7 < ema14 < ema28 < ema200
        if change_pct > self._neutral_threshold and bullish_stack:
            return self._record_classification(
                Regime.BULLISH, change_pct=change_pct, ema_values=ema_values
            )
        if change_pct < -self._neutral_threshold and bearish_stack:
            return self._record_classification(
                Regime.BEARISH, change_pct=change_pct, ema_values=ema_values
            )

        logger.info(
            "regime_undefined_mixed_stack",
            ema7=str(ema7),
            ema14=str(ema14),
            ema28=str(ema28),
            ema200=str(ema200),
        )
        return self._record_classification(
            Regime.UNDEFINED, change_pct=change_pct, ema_values=ema_values
        )

    def _record_classification(
        self,
        regime: Regime,
        change_pct: Decimal | None = None,
        ema_values: (
            tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None] | None
        ) = None,
    ) -> Regime:
        """Persist and log a single computed regime result."""
        self._last_regime = regime
        self._last_classified_at = datetime.now(UTC)
        ema7, ema14, ema28, ema200 = ema_values or (None, None, None, None)
        logger.info(
            "regime_classified",
            regime=regime.value,
            change_pct=str(change_pct),
            ema7=str(ema7),
            ema14=str(ema14),
            ema28=str(ema28),
            ema200=str(ema200),
        )
        return regime
