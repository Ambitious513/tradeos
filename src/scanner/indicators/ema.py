"""Exponential moving-average calculation for closed candle prices."""

from decimal import Decimal

from scanner.models import Candle


def ema(candles: list[Candle], period: int) -> Decimal | None:
    """Compute a Decimal EMA with an SMA seed over closed candle prices.

    Source: tasks/active/TASK_006_INDICATORS.md R-001.
    """
    _validate_period(period)
    if not candles or len(candles) < period:
        return None

    multiplier = Decimal(2) / Decimal(period + 1)
    current_ema = sum(
        (candle.close for candle in candles[:period]), start=Decimal(0)
    ) / Decimal(period)
    for candle in candles[period:]:
        current_ema = candle.close * multiplier + current_ema * (
            Decimal(1) - multiplier
        )
    return current_ema


def _validate_period(period: int) -> None:
    """Reject non-positive indicator periods consistently."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
