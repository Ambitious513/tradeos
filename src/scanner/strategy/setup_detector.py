"""Pure, Decimal-based exhaustion-setup detection functions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from scanner.config import ScannerConfig
from scanner.indicators import atr, ema, rsi
from scanner.models import Candle, Direction

_LEVEL_PROXIMITY_PCT = Decimal("0.5")
_WICK_MULTIPLIER = Decimal("1.5")
_SWEEP_DEPTH_PCT = Decimal("0.1")
_STRUCTURAL_STOP_BUFFER = Decimal("0.001")
_ATR_STOP_MULTIPLIER = Decimal("1.5")
_TAKE_PROFIT_RR = Decimal("2.0")


@dataclass(frozen=True)
class SetupContext:
    """Carry the computed values for one potential SHORT or LONG setup."""

    symbol: str
    direction: Direction
    detected_at: datetime
    change_24h_pct: Decimal
    high_24h: Decimal
    low_24h: Decimal
    rsi_14: float
    ema_7: Decimal
    ema_extension_pct: Decimal
    atr_14: Decimal
    trigger_candle: Candle


def compute_24h_stats(
    candles: list[Candle],
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Compute the rolling 24H high, low, and close-change percentage.

    Source: tasks/active/TASK_008_SETUP_DETECTOR.md R-002.
    """
    if len(candles) < 25:
        return None
    reference_close = candles[-25].close
    if reference_close == 0:
        return None
    window = candles[-24:]
    high_24h = max(candle.high for candle in window)
    low_24h = min(candle.low for candle in window)
    change_pct = (candles[-1].close - reference_close) / reference_close * Decimal(100)
    return high_24h, low_24h, change_pct


def detect_initial_conditions(
    candles: list[Candle], direction: Direction, config: ScannerConfig
) -> SetupContext | None:
    """Return setup context when all initial directional conditions are met.

    Source: STRATEGY_SPEC.md SHORT-001..003 and LONG-001..003.
    """
    if len(candles) < 28:
        return None
    stats = compute_24h_stats(candles)
    rsi_14 = rsi(candles, period=14)
    ema_7 = ema(candles, period=7)
    atr_14 = atr(candles, period=14)
    if stats is None or rsi_14 is None or ema_7 is None or atr_14 is None:
        return None

    extension_pct = compute_ema_extension(candles[-1].close, ema_7, direction)
    if extension_pct is None:
        return None

    high_24h, low_24h, change_24h_pct = stats
    rsi_decimal = Decimal(str(rsi_14))
    if direction is Direction.SHORT:
        conditions_met = (
            change_24h_pct >= Decimal(str(config.pump_threshold_pct))
            and rsi_decimal >= Decimal(str(config.rsi_overbought))
            and extension_pct >= Decimal(str(config.ema7_extension_pct))
        )
    else:
        conditions_met = (
            change_24h_pct <= -Decimal(str(config.dump_threshold_pct))
            and rsi_decimal <= Decimal(str(config.rsi_oversold))
            and extension_pct >= Decimal(str(config.ema7_extension_pct))
        )
    if not conditions_met:
        return None

    trigger_candle = candles[-1]
    return SetupContext(
        symbol=trigger_candle.symbol,
        direction=direction,
        detected_at=trigger_candle.open_time,
        change_24h_pct=change_24h_pct,
        high_24h=high_24h,
        low_24h=low_24h,
        rsi_14=rsi_14,
        ema_7=ema_7,
        ema_extension_pct=extension_pct,
        atr_14=atr_14,
        trigger_candle=trigger_candle,
    )


def compute_ema_extension(
    close: Decimal, ema_7: Decimal, direction: Direction
) -> Decimal | None:
    """Compute the directional percentage extension from EMA7 using Decimal."""
    if ema_7 == 0:
        return None
    if direction is Direction.SHORT:
        return (close - ema_7) / ema_7 * Decimal(100)
    return (ema_7 - close) / ema_7 * Decimal(100)


def check_24h_level_interaction(
    candle: Candle, level_24h: Decimal, direction: Direction
) -> bool:
    """Check proximity to the directional 24H high or low level."""
    if level_24h == 0:
        return False
    if direction is Direction.SHORT:
        proximity_pct = (level_24h - candle.high) / level_24h * Decimal(100)
    else:
        proximity_pct = (candle.low - level_24h) / level_24h * Decimal(100)
    return proximity_pct <= _LEVEL_PROXIMITY_PCT


def check_rejection_candle(candle: Candle, high_24h: Decimal) -> bool:
    """Detect a bearish rejection candle at the rolling 24H high."""
    body = candle.open - candle.close
    if body <= 0:
        return False
    upper_wick = candle.high - candle.open
    return upper_wick >= _WICK_MULTIPLIER * body and check_24h_level_interaction(
        candle, high_24h, Direction.SHORT
    )


def check_liquidity_sweep(candle: Candle, low_24h: Decimal) -> bool:
    """Detect a downside liquidity sweep that closes back above the 24H low."""
    if low_24h == 0:
        return False
    sweep_depth_pct = (low_24h - candle.low) / low_24h * Decimal(100)
    return sweep_depth_pct >= _SWEEP_DEPTH_PCT and candle.close > low_24h


def check_bullish_rejection_candle(candle: Candle, low_24h: Decimal) -> bool:
    """Detect a bullish rejection candle paired with a valid liquidity sweep."""
    body = candle.close - candle.open
    if body <= 0:
        return False
    lower_wick = candle.open - candle.low
    return lower_wick >= _WICK_MULTIPLIER * body and check_liquidity_sweep(
        candle, low_24h
    )


def check_retest_short(
    candle: Candle, rejection_close: Decimal, high_24h: Decimal
) -> bool:
    """Detect a failed SHORT recovery that remains below the 24H high."""
    if rejection_close == 0:
        return False
    proximity_pct = abs(candle.high - rejection_close) / rejection_close * Decimal(100)
    return (
        proximity_pct <= _LEVEL_PROXIMITY_PCT
        and candle.close < rejection_close
        and candle.high < high_24h
    )


def check_retest_long(
    candle: Candle, rejection_close: Decimal, low_24h: Decimal
) -> bool:
    """Detect a LONG pullback that holds above the rolling 24H low."""
    if rejection_close == 0:
        return False
    proximity_pct = abs(candle.low - rejection_close) / rejection_close * Decimal(100)
    return (
        proximity_pct <= _LEVEL_PROXIMITY_PCT
        and candle.close > rejection_close
        and candle.low > low_24h
    )


def check_entry_trigger_short(candle: Candle, retest_low: Decimal) -> bool:
    """Return whether a candle closes below the SHORT retest low."""
    return candle.close < retest_low


def check_entry_trigger_long(candle: Candle, retest_high: Decimal) -> bool:
    """Return whether a candle closes above the LONG retest high."""
    return candle.close > retest_high


def compute_stop_short(
    entry_price: Decimal, recent_candles: list[Candle], atr_14: Decimal
) -> Decimal:
    """Compute the higher, wider SHORT stop from structural and ATR stops."""
    structural_stop = max(candle.high for candle in recent_candles[-3:]) + (
        _STRUCTURAL_STOP_BUFFER * entry_price
    )
    atr_stop = entry_price + (_ATR_STOP_MULTIPLIER * atr_14)
    return max(structural_stop, atr_stop)


def compute_stop_long(
    entry_price: Decimal, recent_candles: list[Candle], atr_14: Decimal
) -> Decimal:
    """Compute the lower, wider LONG stop from structural and ATR stops."""
    structural_stop = min(candle.low for candle in recent_candles[-3:]) - (
        _STRUCTURAL_STOP_BUFFER * entry_price
    )
    atr_stop = entry_price - (_ATR_STOP_MULTIPLIER * atr_14)
    return min(structural_stop, atr_stop)


def compute_take_profit(
    entry_price: Decimal, stop_price: Decimal, direction: Direction
) -> Decimal:
    """Compute a fixed two-to-one reward target from the directional stop."""
    if direction is Direction.SHORT:
        risk_distance = stop_price - entry_price
        return entry_price - (_TAKE_PROFIT_RR * risk_distance)
    risk_distance = entry_price - stop_price
    return entry_price + (_TAKE_PROFIT_RR * risk_distance)


def check_minimum_rr(
    entry_price: Decimal,
    stop_price: Decimal,
    take_profit: Decimal,
    direction: Direction,
    min_rr: Decimal = Decimal("2.0"),
) -> bool:
    """Return whether absolute reward divided by risk meets ``min_rr``."""
    del direction
    reward = abs(take_profit - entry_price)
    risk = abs(stop_price - entry_price)
    if risk == 0:
        return False
    return reward / risk >= min_rr


def compute_avg_volume(candles: list[Candle], period: int = 20) -> Decimal | None:
    """Compute the simple Decimal average volume over the newest candles."""
    if len(candles) < period:
        return None
    return sum(
        (candle.volume for candle in candles[-period:]), start=Decimal(0)
    ) / Decimal(period)
