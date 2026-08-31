"""Core immutable data contracts with no persistence dependencies."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Candle:
    """A normalized OHLCV candle supplied by the market-data layer."""

    symbol: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    is_closed: bool


@dataclass(frozen=True)
class Stats24H:
    """Rolling 24-hour statistics derived from closed candles."""

    symbol: str
    high_24h: Decimal
    low_24h: Decimal
    change_pct_24h: float
    volume_24h_usd: Decimal
    timestamp: datetime


class Regime(str, Enum):
    """Approved BTC market-regime classifications."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNDEFINED = "UNDEFINED"


class Direction(str, Enum):
    """Permitted trade directions."""

    LONG = "LONG"
    SHORT = "SHORT"


class SignalState(str, Enum):
    """Lifecycle states for a setup or signal."""

    DETECTED = "DETECTED"
    WATCHING = "WATCHING"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    ACTIVE = "ACTIVE"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES: frozenset[SignalState] = frozenset(
    {
        SignalState.TP_HIT,
        SignalState.SL_HIT,
        SignalState.EXPIRED,
        SignalState.CANCELLED,
    }
)
