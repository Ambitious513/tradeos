"""Synthetic, pure-function tests for exhaustion setup detection."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from scanner.config import ScannerConfig
from scanner.models import Candle, Direction
from scanner.strategy import (
    SetupContext,
    check_bullish_rejection_candle,
    check_entry_trigger_long,
    check_entry_trigger_short,
    check_liquidity_sweep,
    check_minimum_rr,
    check_rejection_candle,
    check_retest_long,
    check_retest_short,
    compute_24h_stats,
    compute_avg_volume,
    compute_stop_long,
    compute_stop_short,
    compute_take_profit,
    detect_initial_conditions,
)

BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def make_candle(
    index: int,
    *,
    open_price: Decimal | int | str = 100,
    high: Decimal | int | str = 101,
    low: Decimal | int | str = 99,
    close: Decimal | int | str = 100,
    volume: Decimal | int | str = 10,
) -> Candle:
    """Create one closed synthetic 1H candle with explicit OHLCV values."""
    return Candle(
        symbol="TESTUSDT",
        timeframe="60",
        open_time=BASE_TIME + timedelta(hours=index),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        turnover=Decimal(volume) * Decimal(close),
        is_closed=True,
    )


def candles_from_closes(closes: list[Decimal | int | str]) -> list[Candle]:
    """Create chronological candles whose default OHLC values follow each close."""
    return [
        make_candle(
            index,
            open_price=close,
            high=Decimal(close) + Decimal(1),
            low=Decimal(close) - Decimal(1),
            close=close,
        )
        for index, close in enumerate(closes)
    ]


def short_candidate_candles(final_close: Decimal = Decimal("108")) -> list[Candle]:
    """Return 28 candles with a final upward impulse for SHORT detection."""
    return candles_from_closes([Decimal("100")] * 27 + [final_close])


def long_candidate_candles(final_close: Decimal = Decimal("92")) -> list[Candle]:
    """Return 28 candles with a final downward impulse for LONG detection."""
    return candles_from_closes([Decimal("100")] * 27 + [final_close])


def test_short_initial_conditions_all_met_returns_setup_context() -> None:
    """A pumped, overbought, EMA-extended symbol produces a SHORT context."""
    context = detect_initial_conditions(
        short_candidate_candles(), Direction.SHORT, ScannerConfig(_env_file=None)
    )
    assert isinstance(context, SetupContext)
    assert context.direction is Direction.SHORT


def test_short_rejects_when_pump_below_8_pct() -> None:
    """A 7.9% 24H gain fails the inclusive +8% pump threshold."""
    context = detect_initial_conditions(
        short_candidate_candles(Decimal("107.9")),
        Direction.SHORT,
        ScannerConfig(_env_file=None),
    )
    assert context is None


def test_short_rejects_when_rsi_below_75() -> None:
    """A sub-threshold RSI fails despite sufficient price extension."""
    with patch("scanner.strategy.setup_detector.rsi", return_value=74.9):
        context = detect_initial_conditions(
            short_candidate_candles(), Direction.SHORT, ScannerConfig(_env_file=None)
        )
    assert context is None


def test_short_rejects_when_ema_extension_below_3_pct() -> None:
    """An EMA extension below 3% cannot start a SHORT setup."""
    with patch("scanner.strategy.setup_detector.ema", return_value=Decimal("106")):
        context = detect_initial_conditions(
            short_candidate_candles(), Direction.SHORT, ScannerConfig(_env_file=None)
        )
    assert context is None


def test_long_initial_conditions_all_met_returns_setup_context() -> None:
    """A dumped, oversold, EMA-extended symbol produces a LONG context."""
    context = detect_initial_conditions(
        long_candidate_candles(), Direction.LONG, ScannerConfig(_env_file=None)
    )
    assert isinstance(context, SetupContext)
    assert context.direction is Direction.LONG


def test_long_rejects_when_dump_above_neg_8_pct() -> None:
    """A -7.9% 24H change is not a qualifying -8% dump."""
    context = detect_initial_conditions(
        long_candidate_candles(Decimal("92.1")),
        Direction.LONG,
        ScannerConfig(_env_file=None),
    )
    assert context is None


def test_long_rejects_when_rsi_above_25() -> None:
    """A value above the oversold threshold rejects the LONG setup."""
    with patch("scanner.strategy.setup_detector.rsi", return_value=25.1):
        context = detect_initial_conditions(
            long_candidate_candles(), Direction.LONG, ScannerConfig(_env_file=None)
        )
    assert context is None


def test_long_rejects_when_ema_extension_below_3_pct_below_ema() -> None:
    """A sub-3% price-to-EMA distance fails LONG initial detection."""
    with patch("scanner.strategy.setup_detector.ema", return_value=Decimal("94")):
        context = detect_initial_conditions(
            long_candidate_candles(), Direction.LONG, ScannerConfig(_env_file=None)
        )
    assert context is None


def test_insufficient_candles_returns_none() -> None:
    """Twenty-seven candles cannot satisfy the RSI and ATR warmup requirement."""
    assert (
        detect_initial_conditions(
            short_candidate_candles()[:-1],
            Direction.SHORT,
            ScannerConfig(_env_file=None),
        )
        is None
    )


def test_exactly_28_candles_passes_warmup() -> None:
    """Twenty-eight closed candles are sufficient for indicator warmup."""
    assert (
        detect_initial_conditions(
            short_candidate_candles(), Direction.SHORT, ScannerConfig(_env_file=None)
        )
        is not None
    )


def test_rsi_75_inclusive_short_qualifies() -> None:
    """RSI exactly 75.0 meets the approved inclusive SHORT threshold."""
    with patch("scanner.strategy.setup_detector.rsi", return_value=75.0):
        assert (
            detect_initial_conditions(
                short_candidate_candles(),
                Direction.SHORT,
                ScannerConfig(_env_file=None),
            )
            is not None
        )


def test_rsi_25_inclusive_long_qualifies() -> None:
    """RSI exactly 25.0 meets the approved inclusive LONG threshold."""
    with patch("scanner.strategy.setup_detector.rsi", return_value=25.0):
        assert (
            detect_initial_conditions(
                long_candidate_candles(), Direction.LONG, ScannerConfig(_env_file=None)
            )
            is not None
        )


def test_pump_8pct_inclusive_short_qualifies() -> None:
    """A +8.0% change exactly satisfies SHORT-001."""
    assert (
        detect_initial_conditions(
            short_candidate_candles(Decimal("108")),
            Direction.SHORT,
            ScannerConfig(_env_file=None),
        )
        is not None
    )


def test_dump_neg_8pct_inclusive_long_qualifies() -> None:
    """A -8.0% change exactly satisfies LONG-001."""
    assert (
        detect_initial_conditions(
            long_candidate_candles(Decimal("92")),
            Direction.LONG,
            ScannerConfig(_env_file=None),
        )
        is not None
    )


def test_24h_stats_correct_high_low_change() -> None:
    """Stats use the newest 24 candles and the close exactly 24H ago."""
    candles = candles_from_closes([100] + list(range(101, 124)) + [130])
    high, low, change = compute_24h_stats(candles) or (None, None, None)
    assert (high, low, change) == (Decimal("131"), Decimal("100"), Decimal("30"))


def test_rejection_candle_short_all_conditions_met() -> None:
    """Bearish close, 1.5x upper wick, and high interaction form rejection."""
    candle = make_candle(0, open_price=100, high=103, low=98, close=98)
    assert check_rejection_candle(candle, Decimal("103")) is True


def test_rejection_candle_short_bullish_close_rejected() -> None:
    """A bullish close cannot be a SHORT rejection candle."""
    candle = make_candle(0, open_price=100, high=103, low=98, close=101)
    assert check_rejection_candle(candle, Decimal("103")) is False


def test_rejection_candle_short_insufficient_wick_rejected() -> None:
    """An upper wick below 1.5 times the body is rejected."""
    candle = make_candle(0, open_price=100, high=102.9, low=98, close=98)
    assert check_rejection_candle(candle, Decimal("103")) is False


def test_rejection_candle_doji_body_zero_rejected() -> None:
    """A doji is always rejected even when it touches the 24H high."""
    candle = make_candle(0, open_price=100, high=105, low=95, close=100)
    assert check_rejection_candle(candle, Decimal("105")) is False


def test_liquidity_sweep_valid_closes_above_low() -> None:
    """A 0.2% sweep below the low that recovers above it is valid."""
    candle = make_candle(0, open_price=100, high=101, low=99.8, close=100.5)
    assert check_liquidity_sweep(candle, Decimal("100")) is True


def test_liquidity_sweep_no_recovery_rejected() -> None:
    """Closing at or below the old low fails sweep recovery."""
    candle = make_candle(0, open_price=100, high=101, low=99.8, close=100)
    assert check_liquidity_sweep(candle, Decimal("100")) is False


def test_liquidity_sweep_depth_below_0_1pct_rejected() -> None:
    """A sweep shallower than 0.1% does not qualify."""
    candle = make_candle(0, open_price=100, high=101, low=99.95, close=100.5)
    assert check_liquidity_sweep(candle, Decimal("100")) is False


def test_bullish_rejection_candle_all_conditions_met() -> None:
    """Bullish reversal requires both lower wick and accepted liquidity sweep."""
    candle = make_candle(0, open_price=100, high=103, low=97, close=102)
    assert check_bullish_rejection_candle(candle, Decimal("100")) is True


def test_retest_short_valid() -> None:
    """A close below resistance without a new 24H high is a valid SHORT retest."""
    candle = make_candle(0, open_price=99.8, high=100.4, low=98, close=99)
    assert check_retest_short(candle, Decimal("100"), Decimal("101")) is True


def test_retest_short_new_24h_high_rejected() -> None:
    """Touching or exceeding the 24H high invalidates a SHORT retest."""
    candle = make_candle(0, open_price=100, high=101, low=98, close=99)
    assert check_retest_short(candle, Decimal("100"), Decimal("101")) is False


def test_retest_long_valid() -> None:
    """A close above support without a new 24H low is a valid LONG retest."""
    candle = make_candle(0, open_price=100.2, high=102, low=99.6, close=101)
    assert check_retest_long(candle, Decimal("100"), Decimal("99")) is True


def test_retest_long_new_24h_low_rejected() -> None:
    """Touching or breaching the 24H low invalidates a LONG retest."""
    candle = make_candle(0, open_price=100, high=102, low=99, close=101)
    assert check_retest_long(candle, Decimal("100"), Decimal("99")) is False


def test_entry_trigger_short_close_below_retest_low() -> None:
    """A close strictly below the retest low triggers the SHORT entry."""
    assert check_entry_trigger_short(make_candle(0, close=98), Decimal("99")) is True


def test_entry_trigger_short_close_above_rejected() -> None:
    """A close at or above the retest low cannot trigger a SHORT entry."""
    assert check_entry_trigger_short(make_candle(0, close=99), Decimal("99")) is False


def test_entry_trigger_long_close_above_retest_high() -> None:
    """A close strictly above the retest high triggers the LONG entry."""
    assert check_entry_trigger_long(make_candle(0, close=102), Decimal("101")) is True


def test_entry_trigger_long_close_below_rejected() -> None:
    """A close at or below the retest high cannot trigger a LONG entry."""
    assert check_entry_trigger_long(make_candle(0, close=101), Decimal("101")) is False


def test_stop_short_uses_max_of_structural_and_atr() -> None:
    """The higher ATR stop wins when it is farther above entry."""
    recent = [make_candle(index, high=101) for index in range(3)]
    assert compute_stop_short(Decimal("100"), recent, Decimal("1")) == Decimal("101.5")


def test_stop_long_uses_min_of_structural_and_atr() -> None:
    """The lower ATR stop wins when it is farther below entry."""
    recent = [make_candle(index, low=99) for index in range(3)]
    assert compute_stop_long(Decimal("100"), recent, Decimal("1")) == Decimal("98.5")


def test_stop_short_structural_wider_than_atr() -> None:
    """The higher structural stop wins over a tighter ATR stop for SHORT."""
    recent = [make_candle(index, high=101) for index in range(3)]
    assert compute_stop_short(Decimal("100"), recent, Decimal("0.5")) == Decimal(
        "101.1"
    )


def test_stop_long_structural_wider_than_atr() -> None:
    """The lower structural stop wins over a tighter ATR stop for LONG."""
    recent = [make_candle(index, low=98) for index in range(3)]
    assert compute_stop_long(Decimal("100"), recent, Decimal("0.5")) == Decimal("97.9")


def test_take_profit_short_correct_formula() -> None:
    """SHORT take profit is two risk distances below entry."""
    assert compute_take_profit(
        Decimal("100"), Decimal("102"), Direction.SHORT
    ) == Decimal("96")


def test_take_profit_long_correct_formula() -> None:
    """LONG take profit is two risk distances above entry."""
    assert compute_take_profit(
        Decimal("100"), Decimal("98"), Direction.LONG
    ) == Decimal("104")


def test_minimum_rr_2_to_1_returns_true() -> None:
    """Exactly 2:1 reward to risk meets the inclusive minimum."""
    assert (
        check_minimum_rr(Decimal("100"), Decimal("102"), Decimal("96"), Direction.SHORT)
        is True
    )


def test_minimum_rr_below_2_returns_false() -> None:
    """A 1.9:1 target fails the required minimum R:R."""
    assert (
        check_minimum_rr(
            Decimal("100"), Decimal("102"), Decimal("96.2"), Direction.SHORT
        )
        is False
    )


def test_minimum_rr_degenerate_zero_risk_returns_false() -> None:
    """An entry-equals-stop calculation is not a valid reward-to-risk setup."""
    assert (
        check_minimum_rr(Decimal("100"), Decimal("100"), Decimal("96"), Direction.SHORT)
        is False
    )


def test_avg_volume_correct_period() -> None:
    """Only the newest 20 volumes contribute to the scoring helper."""
    candles = [make_candle(index, volume=index + 1) for index in range(25)]
    assert compute_avg_volume(candles) == Decimal("15.5")


def test_avg_volume_insufficient_candles_returns_none() -> None:
    """Volume confirmation waits for a full rolling period."""
    assert compute_avg_volume([make_candle(index) for index in range(19)]) is None
