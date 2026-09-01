"""Synchronous unit tests for BTC 4H regime classification."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from structlog.testing import capture_logs

from scanner.config import ScannerConfig
from scanner.models import Candle, Regime
from scanner.regime import RegimeDetector

BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def make_candles(closes: list[Decimal | int | str]) -> list[Candle]:
    """Create chronological BTC 4H candles from a deterministic close series."""
    return [
        Candle(
            symbol="BTCUSDT",
            timeframe="240",
            open_time=BASE_TIME + timedelta(hours=index * 4),
            open=Decimal(close),
            high=Decimal(close) + Decimal(1),
            low=Decimal(close) - Decimal(1),
            close=Decimal(close),
            volume=Decimal(1),
            turnover=Decimal(1),
            is_closed=True,
        )
        for index, close in enumerate(closes)
    ]


def closes_with_24h_change(last_close: Decimal) -> list[Candle]:
    """Return 200 candles whose final six 4H intervals reach ``last_close``."""
    start = Decimal("100")
    step = (last_close - start) / Decimal(6)
    recent = [start + step * Decimal(index) for index in range(7)]
    return make_candles([start] * 193 + recent)


def detector_for(candles: list[Candle]) -> tuple[RegimeDetector, MagicMock]:
    """Return a detector with a mocked CandleStore read interface."""
    candle_store = MagicMock()
    candle_store.get_closed_candles.return_value = candles
    return RegimeDetector(candle_store, ScannerConfig(_env_file=None)), candle_store


def test_undefined_when_fewer_than_200_candles() -> None:
    """EMA200 warmup requires all 200 BTC 4H candles."""
    detector, _ = detector_for(make_candles([100] * 199))
    assert detector.classify() is Regime.UNDEFINED


def test_neutral_when_change_within_positive_1_5_pct() -> None:
    """A +1% proxy change is inside the inclusive neutral zone."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("101")))
    assert detector.classify() is Regime.NEUTRAL


def test_neutral_when_change_within_negative_1_5_pct() -> None:
    """A -1% proxy change is inside the inclusive neutral zone."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("99")))
    assert detector.classify() is Regime.NEUTRAL


def test_neutral_at_exact_boundary_1_5_pct() -> None:
    """The +1.5% neutral boundary remains neutral, not bullish."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("101.5")))
    assert detector.classify() is Regime.NEUTRAL


def test_undefined_when_change_exceeds_pump_threshold_8_pct() -> None:
    """An extreme positive 24H proxy change blocks trading regardless of stack."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("108.1")))
    assert detector.classify() is Regime.UNDEFINED


def test_undefined_when_change_below_dump_threshold_neg_8_pct() -> None:
    """An extreme negative 24H proxy change blocks trading regardless of stack."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("91.9")))
    assert detector.classify() is Regime.UNDEFINED


def test_bullish_regime_when_stack_aligned_and_positive_change() -> None:
    """A +3% BTC move with a fully rising EMA stack is bullish."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("103")))
    assert detector.classify() is Regime.BULLISH


def test_bearish_regime_when_stack_aligned_and_negative_change() -> None:
    """A -3% BTC move with a fully falling EMA stack is bearish."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("97")))
    assert detector.classify() is Regime.BEARISH


def test_undefined_when_ema_stack_partially_mixed() -> None:
    """Any stack that is neither strictly rising nor falling is undefined."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("103")))
    with patch(
        "scanner.regime.detector.ema",
        side_effect=[Decimal("105"), Decimal("100"), Decimal("102"), Decimal("99")],
    ):
        assert detector.classify() is Regime.UNDEFINED


def test_undefined_when_ema_returns_none_insufficient_data() -> None:
    """An unavailable EMA makes a non-neutral regime unsafe to classify."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("103")))
    with patch("scanner.regime.detector.ema", return_value=None):
        assert detector.classify() is Regime.UNDEFINED


def test_last_regime_is_undefined_before_first_classify() -> None:
    """The detector starts in its fail-safe regime."""
    detector, _ = detector_for([])
    assert detector.last_regime is Regime.UNDEFINED


def test_last_regime_updated_after_classify_call() -> None:
    """Classification records its newest decision for downstream consumers."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("103")))
    detector.classify()
    assert detector.last_regime is Regime.BULLISH


def test_last_classified_at_is_none_before_classify() -> None:
    """No timestamp exists until a classification attempt occurs."""
    detector, _ = detector_for([])
    assert detector.last_classified_at is None


def test_last_classified_at_set_to_utc_after_classify() -> None:
    """Every classification attempt records a timezone-aware UTC timestamp."""
    detector, _ = detector_for([])
    detector.classify()
    assert detector.last_classified_at is not None
    assert detector.last_classified_at.tzinfo is UTC


def test_regime_logs_info_on_bullish() -> None:
    """Bullish classification logs string-form change and EMA values."""
    detector, _ = detector_for(closes_with_24h_change(Decimal("103")))
    with capture_logs() as logs:
        assert detector.classify() is Regime.BULLISH
    classification = next(
        entry for entry in logs if entry["event"] == "regime_classified"
    )
    assert classification["log_level"] == "info"
    assert classification["change_pct"] == "3.00"
    assert isinstance(classification["ema7"], str)
    assert isinstance(classification["ema200"], str)


def test_regime_logs_info_on_insufficient_data() -> None:
    """Insufficient BTC history emits an explicit informational event."""
    detector, _ = detector_for([])
    with capture_logs() as logs:
        assert detector.classify() is Regime.UNDEFINED
    assert any(
        entry["event"] == "regime_undefined_insufficient_data"
        and entry["log_level"] == "info"
        for entry in logs
    )


def test_classify_does_not_raise_on_empty_store() -> None:
    """An empty CandleStore produces the safe undefined regime."""
    detector, _ = detector_for([])
    assert detector.classify() is Regime.UNDEFINED


def test_classify_rereads_candles_on_every_call() -> None:
    """No TTL cache prevents fresh BTC data from changing the decision."""
    bullish = closes_with_24h_change(Decimal("103"))
    bearish = closes_with_24h_change(Decimal("97"))
    detector, candle_store = detector_for(bullish)
    candle_store.get_closed_candles.side_effect = [bullish, bearish]
    assert detector.classify() is Regime.BULLISH
    assert detector.classify() is Regime.BEARISH
    assert candle_store.get_closed_candles.call_count == 2


def test_undefined_when_24h_reference_close_is_zero() -> None:
    """A zero denominator cannot produce a trustworthy percentage change."""
    candles = closes_with_24h_change(Decimal("103"))
    candles[-7] = candles[-7].__class__(
        symbol=candles[-7].symbol,
        timeframe=candles[-7].timeframe,
        open_time=candles[-7].open_time,
        open=Decimal(0),
        high=Decimal(1),
        low=Decimal(0),
        close=Decimal(0),
        volume=candles[-7].volume,
        turnover=candles[-7].turnover,
        is_closed=True,
    )
    detector, _ = detector_for(candles)
    assert detector.classify() is Regime.UNDEFINED
