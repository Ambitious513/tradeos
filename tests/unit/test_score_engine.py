"""Pure SCORE-001 tests using synthetic setup inputs."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scanner.models import Candle, Direction
from scanner.strategy import ScoreInput, SetupContext, compute_score, is_a_plus


def make_candle(
    *,
    open_price: Decimal | int | str = 100,
    high: Decimal | int | str = 100,
    low: Decimal | int | str = 100,
    close: Decimal | int | str = 100,
    volume: Decimal | int | str = 10,
) -> Candle:
    """Create a closed synthetic candle suitable for deterministic scoring."""
    return Candle(
        symbol="TESTUSDT",
        timeframe="60",
        open_time=datetime(2026, 9, 1, tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        turnover=Decimal(volume) * Decimal(close),
        is_closed=True,
    )


def make_context(
    *,
    direction: Direction = Direction.SHORT,
    change: Decimal | int | str = 0,
    rsi_14: float = 50.0,
    extension: Decimal | int | str = 0,
) -> SetupContext:
    """Create a score-ready context with one selected criterion value."""
    candle = make_candle()
    return SetupContext(
        symbol="TESTUSDT",
        direction=direction,
        detected_at=candle.open_time,
        change_24h_pct=Decimal(change),
        high_24h=Decimal("100"),
        low_24h=Decimal("100"),
        rsi_14=rsi_14,
        ema_7=Decimal("100"),
        ema_extension_pct=Decimal(extension),
        atr_14=Decimal("1"),
        trigger_candle=candle,
    )


def make_score_input(
    *,
    context: SetupContext | None = None,
    rejection: Candle | None = None,
    avg_volume: Decimal | None = None,
    sweep_or_excess: Decimal | int | str = 0,
    entry: Decimal | int | str = 100,
    stop: Decimal | int | str = 100,
    take_profit: Decimal | int | str = 100,
) -> ScoreInput:
    """Create an otherwise zero-tier input for isolated criterion tests."""
    return ScoreInput(
        setup_context=context or make_context(),
        rejection_candle=rejection or make_candle(),
        avg_volume_20=avg_volume,
        sweep_or_excess_pct=Decimal(sweep_or_excess),
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        take_profit=Decimal(take_profit),
    )


def test_btc_regime_alignment_always_awards_20_points() -> None:
    """A valid setup always receives the regime-alignment base score."""
    assert compute_score(make_score_input()) == 20


def test_move_magnitude_highest_tier_awards_15_points() -> None:
    """A 12% move receives only the highest move tier, not cumulative tiers."""
    context = make_context(change=Decimal("12"))
    assert compute_score(make_score_input(context=context)) == 35


def test_move_magnitude_middle_tier_awards_10_points() -> None:
    """A 10% move receives the middle move tier."""
    context = make_context(change=Decimal("10"))
    assert compute_score(make_score_input(context=context)) == 30


def test_move_magnitude_minimum_tier_awards_5_points() -> None:
    """An 8% absolute move receives the inclusive entry tier."""
    context = make_context(change=Decimal("-8"))
    assert compute_score(make_score_input(context=context)) == 25


def test_short_rsi_highest_tier_awards_15_points() -> None:
    """SHORT RSI at 80 receives the highest directional tier."""
    assert compute_score(make_score_input(context=make_context(rsi_14=80.0))) == 35


def test_short_rsi_middle_tier_awards_10_points() -> None:
    """SHORT RSI at 77 receives the middle directional tier."""
    assert compute_score(make_score_input(context=make_context(rsi_14=77.0))) == 30


def test_short_rsi_minimum_tier_awards_5_points() -> None:
    """SHORT RSI at 75 receives the inclusive initial tier."""
    assert compute_score(make_score_input(context=make_context(rsi_14=75.0))) == 25


def test_long_rsi_highest_tier_awards_15_points() -> None:
    """LONG RSI at 20 receives the highest inverse-direction tier."""
    context = make_context(direction=Direction.LONG, rsi_14=20.0)
    assert compute_score(make_score_input(context=context)) == 35


def test_ema_extension_highest_tier_awards_10_points() -> None:
    """A 5% extension receives only its highest matching tier."""
    assert compute_score(make_score_input(context=make_context(extension=5))) == 30


def test_ema_extension_middle_tier_awards_7_points() -> None:
    """A 4% extension receives the middle tier."""
    assert compute_score(make_score_input(context=make_context(extension=4))) == 27


def test_ema_extension_minimum_tier_awards_5_points() -> None:
    """A 3% extension receives the inclusive initial tier."""
    assert compute_score(make_score_input(context=make_context(extension=3))) == 25


def test_sweep_or_excess_highest_tier_awards_10_points() -> None:
    """A 0.5% sweep/excess receives the highest tier."""
    assert compute_score(make_score_input(sweep_or_excess=Decimal("0.5"))) == 30


def test_sweep_or_excess_middle_tier_awards_5_points() -> None:
    """A 0.25% sweep/excess receives the middle tier."""
    assert compute_score(make_score_input(sweep_or_excess=Decimal("0.25"))) == 25


def test_sweep_or_excess_minimum_tier_awards_2_points() -> None:
    """A 0.1% sweep/excess receives the inclusive entry tier."""
    assert compute_score(make_score_input(sweep_or_excess=Decimal("0.1"))) == 22


def test_long_rejection_wick_highest_tier_awards_10_points() -> None:
    """A two-body lower wick receives the highest LONG rejection tier."""
    candle = make_candle(open_price=100, low=96, close=102)
    context = make_context(direction=Direction.LONG)
    assert compute_score(make_score_input(context=context, rejection=candle)) == 30


def test_short_rejection_wick_middle_tier_awards_5_points() -> None:
    """A 1.5-body upper wick receives the middle SHORT rejection tier."""
    candle = make_candle(open_price=100, high=103, close=98)
    assert compute_score(make_score_input(rejection=candle)) == 25


def test_doji_rejection_wick_awards_zero_points() -> None:
    """A bodyless candle cannot earn a wick-quality score."""
    assert compute_score(make_score_input(rejection=make_candle(high=110))) == 20


def test_volume_highest_tier_uses_strict_greater_than() -> None:
    """Volume above 1.5 times average receives ten points."""
    candle = make_candle(volume=Decimal("15.1"))
    assert (
        compute_score(make_score_input(rejection=candle, avg_volume=Decimal("10")))
        == 30
    )


def test_volume_middle_tier_awards_5_points() -> None:
    """Volume above 1.2 but not 1.5 times average receives five points."""
    candle = make_candle(volume=Decimal("12.1"))
    assert (
        compute_score(make_score_input(rejection=candle, avg_volume=Decimal("10")))
        == 25
    )


def test_volume_none_awards_zero_points() -> None:
    """Missing volume history is safely unscored rather than an error."""
    candle = make_candle(volume=Decimal("100"))
    assert compute_score(make_score_input(rejection=candle, avg_volume=None)) == 20


def test_rr_tiers_and_degenerate_risk() -> None:
    """R:R tiers use highest matches and reject a zero-risk stop."""
    assert compute_score(make_score_input(stop=102, take_profit=94)) == 30
    assert compute_score(make_score_input(stop=102, take_profit=95)) == 27
    assert compute_score(make_score_input(stop=102, take_profit=96)) == 25
    assert compute_score(make_score_input(stop=100, take_profit=94)) == 20


def test_is_a_plus_uses_inclusive_80_point_threshold() -> None:
    """Scores at 80 pass while scores just below it do not."""
    assert is_a_plus(80) is True
    assert is_a_plus(79) is False


def test_maximum_score_is_100() -> None:
    """All highest tiers sum to the SCORE-001 maximum without overflow."""
    context = make_context(change=12, rsi_14=80.0, extension=5)
    candle = make_candle(open_price=100, high=104, close=98, volume=16)
    score_input = make_score_input(
        context=context,
        rejection=candle,
        avg_volume=Decimal("10"),
        sweep_or_excess=Decimal("0.5"),
        stop=Decimal("102"),
        take_profit=Decimal("94"),
    )
    assert compute_score(score_input) == 100


def test_score_input_is_frozen() -> None:
    """Score inputs remain immutable after creation."""
    score_input = make_score_input()
    with pytest.raises(FrozenInstanceError):
        score_input.entry_price = Decimal("101")
