"""Deterministic tests for immutable T011 risk sizing and daily limits."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from structlog.testing import capture_logs

from scanner.config import ScannerConfig
from scanner.market_data.models import SymbolInfo
from scanner.models import Direction
from scanner.risk import DailySession, RiskEngine


def engine(**overrides: float) -> RiskEngine:
    """Build an engine with approved defaults and optional test-only rates."""
    return RiskEngine(ScannerConfig(_env_file=None, **overrides))


def symbol_info(
    tick_size: str = "0.01", lot_size: str = "0.01", min_qty: str = "0.01"
) -> SymbolInfo:
    """Build fixed exchange metadata for risk calculations."""
    return SymbolInfo(
        symbol="SOLUSDT",
        base_coin="SOL",
        quote_coin="USDT",
        status="Trading",
        tick_size=Decimal(tick_size),
        lot_size=Decimal(lot_size),
        min_order_qty=Decimal(min_qty),
        max_leverage=50.0,
        contract_type="LinearPerpetual",
    )


def daily(**overrides: object) -> DailySession:
    """Build a clear daily session without mutating it during approval."""
    return DailySession(date(2026, 9, 1), **overrides)


def approve_short(
    risk_engine: RiskEngine | None = None,
    info: SymbolInfo | None = None,
    session: DailySession | None = None,
) -> object:
    """Run the contract's known short calculation through the full pipeline."""
    return (risk_engine or engine()).approve(
        Decimal("100"),
        Decimal("102"),
        Decimal("96"),
        Direction.SHORT,
        info or symbol_info(),
        session or daily(),
    )


def test_known_position_size_calculation() -> None:
    """RISK_SPEC §2's known values produce exactly 2.50 contracts."""
    decision = approve_short()
    assert decision.approved
    assert decision.calculation is not None
    assert decision.calculation.risk_distance_pct == Decimal("0.02")
    assert decision.calculation.position_size_usdt == Decimal("250")
    assert decision.calculation.qty == Decimal("2.50")


def test_qty_floored_to_lot_size_not_rounded_up() -> None:
    """A fractional lot is floored rather than rounded up beyond fixed risk."""
    decision = approve_short(info=symbol_info(lot_size="0.3", min_qty="0.01"))
    assert decision.calculation is not None
    assert decision.calculation.qty == Decimal("2.4")


def test_qty_exactly_on_lot_size_boundary() -> None:
    """An exact increment remains unchanged by lot-size flooring."""
    decision = approve_short(info=symbol_info(lot_size="0.5"))
    assert decision.calculation is not None
    assert decision.calculation.qty == Decimal("2.5")


def test_rejected_when_qty_below_min_order_qty() -> None:
    """Exchange minimum quantity is a hard pre-viability rejection."""
    decision = approve_short(info=symbol_info(min_qty="3"))
    assert not decision.approved
    assert decision.reason == "position size below minimum"


def test_daily_halt_flag_rejects() -> None:
    """An externally halted daily session is never approved."""
    session = daily(is_halted=True, halt_reason="operator halt")
    decision = approve_short(session=session)
    assert not decision.approved
    assert decision.reason == "operator halt"


def test_trades_taken_5_rejects() -> None:
    """The inclusive five-trade daily maximum rejects another setup."""
    decision = approve_short(session=daily(trades_taken=5))
    assert decision.reason == "Daily trade limit reached"


def test_trades_taken_4_passes() -> None:
    """Four trades remain below the immutable daily ceiling."""
    assert approve_short(session=daily(trades_taken=4)).approved


def test_realized_pnl_at_loss_limit_rejects() -> None:
    """The loss threshold is inclusive at negative twenty-five dollars."""
    decision = approve_short(session=daily(realized_pnl=Decimal("-25.00")))
    assert decision.reason == "Daily loss limit reached"


def test_realized_pnl_just_above_loss_limit_passes() -> None:
    """A loss short of the exact limit remains eligible."""
    assert approve_short(session=daily(realized_pnl=Decimal("-24.99"))).approved


def test_realized_pnl_at_profit_lock_rejects() -> None:
    """The profit lock is inclusive at positive fifty dollars."""
    decision = approve_short(session=daily(realized_pnl=Decimal("50.00")))
    assert decision.reason == "Daily profit lock triggered"


def test_short_stop_below_entry_geometry_rejected() -> None:
    """A SHORT stop cannot sit below its entry price."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("98"),
        Decimal("96"),
        Direction.SHORT,
        symbol_info(),
        daily(),
    )
    assert decision.reason == "short stop must be above entry"


def test_long_stop_above_entry_geometry_rejected() -> None:
    """A LONG stop cannot sit above its entry price."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("102"),
        Decimal("104"),
        Direction.LONG,
        symbol_info(),
        daily(),
    )
    assert decision.reason == "long stop must be below entry"


def test_entry_equals_stop_zero_distance_rejected() -> None:
    """Zero stop distance is rejected before Decimal division."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("100"),
        Decimal("96"),
        Direction.SHORT,
        symbol_info(),
        daily(),
    )
    assert decision.reason == "risk distance must be positive"


def test_short_stop_rounded_ceil_to_tick() -> None:
    """A short protective stop rounds upward to the wider tick."""
    decision = engine().calculate(
        Decimal("100"),
        Decimal("102.01"),
        Decimal("95"),
        Direction.SHORT,
        symbol_info(tick_size="0.1"),
    )
    assert decision.calculation is not None
    assert decision.calculation.stop_price == Decimal("102.1")


def test_long_stop_rounded_floor_to_tick() -> None:
    """A long protective stop rounds downward to the wider tick."""
    decision = engine().calculate(
        Decimal("100"),
        Decimal("97.99"),
        Decimal("105"),
        Direction.LONG,
        symbol_info(tick_size="0.1"),
    )
    assert decision.calculation is not None
    assert decision.calculation.stop_price == Decimal("97.9")


def test_short_tp_rounded_floor_to_tick() -> None:
    """RISK-001 fix: short TP rounds DOWN (away from entry = more reward)."""
    decision = engine().calculate(
        Decimal("100"),
        Decimal("102"),
        Decimal("96.01"),
        Direction.SHORT,
        symbol_info(tick_size="0.1"),
    )
    assert decision.calculation is not None
    assert decision.calculation.take_profit == Decimal("96.0")


def test_long_tp_rounded_ceil_to_tick() -> None:
    """RISK-001 fix: long TP rounds UP (away from entry = more reward)."""
    decision = engine().calculate(
        Decimal("100"),
        Decimal("98"),
        Decimal("103.99"),
        Direction.LONG,
        symbol_info(tick_size="0.1"),
    )
    assert decision.calculation is not None
    assert decision.calculation.take_profit == Decimal("104.0")


def test_fee_is_entry_plus_tp_exit_both_sides() -> None:
    """Fees use the rounded TP as the winning-scenario exit price."""
    decision = approve_short()
    assert decision.calculation is not None
    assert decision.calculation.fee_cost_usd == Decimal("0.269500")


def test_slippage_is_entry_plus_tp_exit_both_sides() -> None:
    """Slippage uses the same entry and take-profit two-sided notional."""
    decision = approve_short()
    assert decision.calculation is not None
    assert decision.calculation.slippage_cost_usd == Decimal("0.24500")


def test_effective_risk_is_risk_plus_fee_plus_slippage() -> None:
    """Effective risk adds fixed risk and both execution-cost components."""
    decision = approve_short()
    assert decision.calculation is not None
    assert decision.calculation.effective_risk_usd == Decimal("5.514500")


def test_effective_risk_above_1_5x_logs_warning() -> None:
    """Abnormally high configured costs log a warning at calculation time."""
    costly = engine(taker_fee_rate=0.03, slippage_rate=0.03)
    with capture_logs() as logs:
        decision = costly.calculate(
            Decimal("100"),
            Decimal("102"),
            Decimal("96"),
            Direction.SHORT,
            symbol_info(),
        )
    assert decision.approved
    assert any(entry["event"] == "effective_risk_wide" for entry in logs)


def test_rr_ratio_at_least_minimum_after_rounding() -> None:
    """RISK-001 fix: post-rounding RR is always >= 2.0 (TP recomputed from rounded stop)."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("102.01"),
        Decimal("95.8"),
        Direction.SHORT,
        symbol_info(tick_size="0.1"),
        daily(),
    )
    assert decision.approved
    assert decision.calculation is not None
    assert decision.calculation.rr_ratio >= Decimal("2")


def test_approve_integrates_all_steps_returns_approved() -> None:
    """The complete daily-to-viability pipeline approves a compliant setup."""
    decision = approve_short()
    assert decision.approved
    assert decision.reason == "approved"
    assert decision.calculation is not None


def test_exception_in_approve_returns_false_not_raise() -> None:
    """Unexpected internal failures follow RISK_SPEC §8 no-trade behavior."""
    risk_engine = engine()
    with patch.object(risk_engine, "calculate", side_effect=ArithmeticError("bad")):
        decision = approve_short(risk_engine)
    assert not decision.approved
    assert decision.reason == "risk_engine_failure: ArithmeticError"


def test_all_price_fields_in_risk_calculation_are_decimal() -> None:
    """The result contains Decimal values for all monetary and ratio fields."""
    decision = approve_short()
    assert decision.calculation is not None
    calculation = decision.calculation
    assert all(
        isinstance(value, Decimal)
        for value in (
            calculation.entry_price,
            calculation.stop_price,
            calculation.take_profit,
            calculation.qty,
            calculation.position_size_usdt,
            calculation.risk_distance_pct,
            calculation.fee_cost_usd,
            calculation.slippage_cost_usd,
            calculation.effective_risk_usd,
            calculation.rr_ratio,
        )
    )


def test_known_short_example_end_to_end() -> None:
    """The documented short example keeps its expected risk and sizing values."""
    decision = approve_short()
    assert decision.approved
    assert decision.calculation is not None
    assert decision.calculation.qty == Decimal("2.50")
    assert decision.calculation.fee_cost_usd == Decimal("0.269500")


def test_known_long_example_end_to_end() -> None:
    """A symmetric long example applies directional geometry and floor sizing."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("98"),
        Decimal("104"),
        Direction.LONG,
        symbol_info(),
        daily(),
    )
    assert decision.approved
    assert decision.calculation is not None
    assert decision.calculation.qty == Decimal("2.50")
    assert decision.calculation.rr_ratio == Decimal("2")


def test_daily_session_halt_method_sets_reason() -> None:
    """The owner can irreversibly persist a human-readable halt reason."""
    session = daily()
    session.halt("manual review")
    assert session.is_halted
    assert session.halt_reason == "manual review"


def test_zero_tick_size_is_rejected_without_raising() -> None:
    """Malformed exchange metadata fails safe instead of dividing by zero."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("102"),
        Decimal("96"),
        Direction.SHORT,
        symbol_info(tick_size="0"),
        daily(),
    )
    assert not decision.approved
    assert decision.reason == "risk_engine_failure: ValueError"


def test_zero_lot_size_is_rejected_without_raising() -> None:
    """A zero lot size cannot create a rounded quantity."""
    decision = engine().approve(
        Decimal("100"),
        Decimal("102"),
        Decimal("96"),
        Direction.SHORT,
        symbol_info(lot_size="0"),
        daily(),
    )
    assert not decision.approved
    assert decision.reason == "lot size must be positive"
