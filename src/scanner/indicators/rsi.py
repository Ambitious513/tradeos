"""Wilder-smoothed relative-strength index calculation."""

from decimal import Decimal

from scanner.models import Candle


def rsi(candles: list[Candle], period: int = 14) -> float | None:
    """Compute RSI using Wilder's smoothed moving averages of price changes.

    Source: tasks/active/TASK_006_INDICATORS.md R-002.
    """
    _validate_period(period)
    if not candles or len(candles) < period + 1:
        return None

    changes = [
        current.close - previous.close
        for previous, current in zip(candles, candles[1:])
    ]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [abs(min(change, Decimal(0))) for change in changes]

    decimal_period = Decimal(period)
    average_gain = sum(gains[:period], start=Decimal(0)) / decimal_period
    average_loss = sum(losses[:period], start=Decimal(0)) / decimal_period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * Decimal(period - 1) + gain) / decimal_period
        average_loss = (average_loss * Decimal(period - 1) + loss) / decimal_period

    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0

    relative_strength = average_gain / average_loss
    return float(Decimal(100) - (Decimal(100) / (Decimal(1) + relative_strength)))


def _validate_period(period: int) -> None:
    """Reject non-positive indicator periods consistently."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
