"""Deterministic tests for pure EMA, RSI, and ATR functions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scanner.indicators import atr, ema, rsi
from scanner.models import Candle

BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def make_candle(
    close: Decimal | int | str,
    index: int,
    *,
    high: Decimal | int | str | None = None,
    low: Decimal | int | str | None = None,
) -> Candle:
    """Create a closed synthetic candle with controllable OHLC values."""
    close_decimal = Decimal(close)
    return Candle(
        symbol="TESTUSDT",
        timeframe="60",
        open_time=BASE_TIME + timedelta(hours=index),
        open=close_decimal,
        high=Decimal(high) if high is not None else close_decimal + Decimal(1),
        low=Decimal(low) if low is not None else close_decimal - Decimal(1),
        close=close_decimal,
        volume=Decimal(1),
        turnover=Decimal(1),
        is_closed=True,
    )


def close_candles(values: list[Decimal | int | str]) -> list[Candle]:
    """Create a chronological sequence with close-based high and low prices."""
    return [make_candle(value, index) for index, value in enumerate(values)]


def test_ema_returns_none_when_insufficient_data() -> None:
    """EMA needs a complete initial SMA seed window."""
    assert ema(close_candles([1, 2, 3]), 4) is None


def test_ema_seed_is_sma_of_first_period_closes() -> None:
    """Exactly one EMA window returns its Decimal SMA seed."""
    assert ema(close_candles([Decimal("1"), Decimal("2"), Decimal("3")]), 3) == Decimal(
        "2"
    )


def test_ema_returns_decimal_not_float() -> None:
    """EMA price arithmetic retains Decimal precision."""
    result = ema(close_candles([1, 2, 3]), 2)
    assert isinstance(result, Decimal)


def test_ema_known_value_5_period() -> None:
    """A hand-computed EMA uses the required SMA seed and multiplier."""
    # SMA(10,20,30,40,50) = 30; k = 2/(5+1) = 1/3;
    # EMA = 60*(1/3) + 30*(2/3) = 40.
    assert ema(close_candles([10, 20, 30, 40, 50, 60]), 5) == Decimal("40")


def test_ema_period_1_equals_last_close() -> None:
    """A one-period EMA assigns full weight to the current closing price."""
    assert ema(close_candles([10, 20, 30]), 1) == Decimal("30")


def test_ema_does_not_mutate_input_list() -> None:
    """EMA leaves caller ordering and contents unchanged."""
    candles = close_candles([10, 20, 30, 40, 50])
    original = list(candles)
    ema(candles, 3)
    assert candles == original


def test_rsi_returns_none_when_insufficient_data() -> None:
    """RSI needs one more close than its change period."""
    assert rsi(close_candles(range(14)), 14) is None


def test_rsi_all_gains_returns_100() -> None:
    """No average loss represents maximum relative strength."""
    assert rsi(close_candles(range(15)), 14) == 100.0


def test_rsi_all_losses_returns_0() -> None:
    """No average gain represents minimum relative strength."""
    assert rsi(close_candles(list(range(15, 0, -1))), 14) == 0.0


def test_rsi_no_movement_returns_50() -> None:
    """A flat price series is neutral rather than overbought or oversold."""
    assert rsi(close_candles([100] * 15), 14) == 50.0


def test_rsi_known_value_14_period() -> None:
    """A hand-computed subsequent update verifies Wilder smoothing."""
    changes = [2, -1] * 7 + [2]
    closes = [Decimal("100")]
    for change in changes:
        closes.append(closes[-1] + Decimal(change))
    # First 14 changes: avg_gain=14/14=1, avg_loss=7/14=1/2.
    # Final +2: gain=(1*13+2)/14=15/14, loss=(1/2*13)/14=13/28.
    # RS=(15/14)/(13/28)=30/13, RSI=100-(100/(1+30/13))=3000/43=69.76744...
    assert rsi(close_candles(closes), 14) == pytest.approx(3000 / 43, abs=0.01)


def test_rsi_value_in_valid_range() -> None:
    """RSI output is always bounded as a percentage."""
    result = rsi(close_candles([100, 102, 99, 103, 101] * 4), 14)
    assert result is not None
    assert 0.0 <= result <= 100.0


def test_atr_returns_none_when_insufficient_data() -> None:
    """ATR needs a prior close for every true range in its seed."""
    assert atr(close_candles(range(3)), 3) is None


def test_atr_true_range_gap_up_uses_prev_close() -> None:
    """A gap above the prior close dominates the intrabar range."""
    candles = [make_candle(10, 0), make_candle(14, 1, high=15, low=14)]
    assert atr(candles, 1) == Decimal("5")


def test_atr_true_range_gap_down_uses_prev_close() -> None:
    """A gap below the prior close dominates the intrabar range."""
    candles = [make_candle(10, 0), make_candle(6, 1, high=7, low=6)]
    assert atr(candles, 1) == Decimal("4")


def test_atr_returns_decimal_not_float() -> None:
    """ATR returns a Decimal price-distance value."""
    result = atr(close_candles([10, 12]), 1)
    assert isinstance(result, Decimal)


def test_atr_known_value_3_period() -> None:
    """A hand-computed sequence verifies true range and Wilder smoothing."""
    candles = [
        make_candle(10, 0),
        make_candle(12, 1, high=13, low=11),
        make_candle(14, 2, high=15, low=12),
        make_candle(15, 3, high=16, low=13),
        make_candle(19, 4, high=20, low=16),
    ]
    # TRs are 3, 3, 3, 5; seed ATR(3)=(3+3+3)/3=3.
    # Wilder update = (3*(3-1)+5)/3 = 11/3.
    assert atr(candles, 3) == Decimal(11) / Decimal(3)


def test_invalid_period_zero_raises_value_error() -> None:
    """All indicators reject a zero-length period."""
    candles = close_candles([1])
    for indicator in (ema, rsi, atr):
        with pytest.raises(ValueError, match="period must be >= 1, got 0"):
            indicator(candles, 0)


def test_invalid_period_negative_raises_value_error() -> None:
    """All indicators reject a negative period."""
    candles = close_candles([1])
    for indicator in (ema, rsi, atr):
        with pytest.raises(ValueError, match="period must be >= 1, got -1"):
            indicator(candles, -1)


def test_empty_candle_list_returns_none() -> None:
    """Empty input is a normal insufficient-data result for all indicators."""
    assert ema([], 1) is None
    assert rsi([], 1) is None
    assert atr([], 1) is None
