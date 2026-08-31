"""Tests for core immutable data models and enums."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scanner.models import Candle, Direction, Regime, SignalState, Stats24H, TERMINAL_STATES


def test_candle_creation(sample_candle: object) -> None:
    """A candle factory returns a normalized closed candle."""
    candle = sample_candle()  # type: ignore[operator]
    assert candle.symbol == "ETHUSDT"
    assert candle.is_closed is True


def test_candle_is_frozen(sample_candle: object) -> None:
    """Candles cannot be altered after normalization."""
    candle = sample_candle()  # type: ignore[operator]
    with pytest.raises(FrozenInstanceError):
        candle.close = Decimal("99")


def test_stats24h_creation() -> None:
    """24-hour statistics retain Decimal monetary values."""
    stats = Stats24H(
        symbol="ETHUSDT",
        high_24h=Decimal("105"),
        low_24h=Decimal("95"),
        change_pct_24h=5.0,
        volume_24h_usd=Decimal("50000000"),
        timestamp=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert stats.volume_24h_usd == Decimal("50000000")


def test_regime_enum_values() -> None:
    """Regime exposes all safe classification outcomes."""
    assert {member.value for member in Regime} == {
        "BULLISH",
        "BEARISH",
        "NEUTRAL",
        "UNDEFINED",
    }


def test_direction_enum_values() -> None:
    """Direction exposes only long and short."""
    assert {member.value for member in Direction} == {"LONG", "SHORT"}


def test_signal_state_enum_all_nine_states() -> None:
    """The signal lifecycle contains all approved states."""
    assert len(SignalState) == 9


def test_terminal_states_set_correct() -> None:
    """Only completed, expired, or cancelled states are terminal."""
    assert TERMINAL_STATES == {
        SignalState.TP_HIT,
        SignalState.SL_HIT,
        SignalState.EXPIRED,
        SignalState.CANCELLED,
    }
