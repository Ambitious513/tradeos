"""Pure A+ scoring from a fully specified setup input."""

from dataclasses import dataclass
from decimal import Decimal

from scanner.models import Candle, Direction
from scanner.strategy.setup_detector import SetupContext


@dataclass(frozen=True)
class ScoreInput:
    """Provide every computed value required by SCORE-001 without I/O."""

    setup_context: SetupContext
    rejection_candle: Candle
    avg_volume_20: Decimal | None
    sweep_or_excess_pct: Decimal
    entry_price: Decimal
    stop_price: Decimal
    take_profit: Decimal


def compute_score(score_input: ScoreInput) -> int:
    """Compute the 0–100 A+ score using the highest matching tier per criterion.

    Source: docs/STRATEGY_SPEC.md SCORE-001.
    """
    context = score_input.setup_context
    return (
        20
        + _score_move_magnitude(abs(context.change_24h_pct))
        + _score_rsi(context.rsi_14, context.direction)
        + _score_ema_extension(context.ema_extension_pct)
        + _score_sweep_or_excess(score_input.sweep_or_excess_pct)
        + _score_rejection_wick(score_input.rejection_candle, context.direction)
        + _score_volume(score_input.rejection_candle, score_input.avg_volume_20)
        + _score_rr(
            score_input.entry_price,
            score_input.stop_price,
            score_input.take_profit,
        )
    )


def is_a_plus(score: int) -> bool:
    """Return whether a score meets the approved 80-point A+ threshold."""
    return score >= 80


def _score_move_magnitude(change_pct: Decimal) -> int:
    """Score absolute 24H move magnitude using descending inclusive tiers."""
    return _score_decimal_tiers(
        change_pct,
        ((Decimal("12"), 15), (Decimal("10"), 10), (Decimal("8"), 5)),
    )


def _score_rsi(rsi_14: float, direction: Direction) -> int:
    """Score directional RSI extremes using the approved inclusive ranges."""
    if direction is Direction.SHORT:
        if rsi_14 >= 80.0:
            return 15
        if rsi_14 >= 77.0:
            return 10
        if rsi_14 >= 75.0:
            return 5
        return 0
    if rsi_14 <= 20.0:
        return 15
    if rsi_14 <= 23.0:
        return 10
    if rsi_14 <= 25.0:
        return 5
    return 0


def _score_ema_extension(extension_pct: Decimal) -> int:
    """Score EMA extension with the highest inclusive matching tier."""
    return _score_decimal_tiers(
        extension_pct,
        ((Decimal("5"), 10), (Decimal("4"), 7), (Decimal("3"), 5)),
    )


def _score_sweep_or_excess(sweep_or_excess_pct: Decimal) -> int:
    """Score directional sweep depth or high excess using inclusive tiers."""
    return _score_decimal_tiers(
        sweep_or_excess_pct,
        ((Decimal("0.5"), 10), (Decimal("0.25"), 5), (Decimal("0.1"), 2)),
    )


def _score_rejection_wick(candle: Candle, direction: Direction) -> int:
    """Score the directional rejection wick as a multiple of its candle body."""
    body = abs(candle.close - candle.open)
    if body == 0:
        return 0
    if direction is Direction.SHORT:
        wick = candle.high - candle.open
    else:
        wick = candle.open - candle.low
    wick_multiple = wick / body
    return _score_decimal_tiers(
        wick_multiple,
        ((Decimal("2"), 10), (Decimal("1.5"), 5)),
    )


def _score_volume(candle: Candle, avg_volume_20: Decimal | None) -> int:
    """Score strict volume confirmation without treating missing history as an error."""
    if avg_volume_20 is None:
        return 0
    if candle.volume > Decimal("1.5") * avg_volume_20:
        return 10
    if candle.volume > Decimal("1.2") * avg_volume_20:
        return 5
    return 0


def _score_rr(entry_price: Decimal, stop_price: Decimal, take_profit: Decimal) -> int:
    """Score reward-to-risk tiers while safely rejecting a zero-risk stop."""
    risk = abs(stop_price - entry_price)
    if risk == 0:
        return 0
    reward_to_risk = abs(take_profit - entry_price) / risk
    return _score_decimal_tiers(
        reward_to_risk,
        ((Decimal("3"), 10), (Decimal("2.5"), 7), (Decimal("2"), 5)),
    )


def _score_decimal_tiers(value: Decimal, tiers: tuple[tuple[Decimal, int], ...]) -> int:
    """Return the first score from descending inclusive Decimal thresholds."""
    for threshold, score in tiers:
        if value >= threshold:
            return score
    return 0
