"""Wilder-smoothed average true-range calculation."""

from decimal import Decimal

from scanner.models import Candle


def atr(candles: list[Candle], period: int = 14) -> Decimal | None:
    """Compute a Decimal ATR using true ranges and Wilder smoothing.

    Source: tasks/active/TASK_006_INDICATORS.md R-003.
    """
    _validate_period(period)
    if not candles or len(candles) < period + 1:
        return None

    true_ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(candles, candles[1:])
    ]
    decimal_period = Decimal(period)
    current_atr = sum(true_ranges[:period], start=Decimal(0)) / decimal_period
    for true_range in true_ranges[period:]:
        current_atr = (current_atr * Decimal(period - 1) + true_range) / decimal_period
    return current_atr


def _validate_period(period: int) -> None:
    """Reject non-positive indicator periods consistently."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
