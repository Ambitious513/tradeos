"""Pure position sizing and viability validation for approved setup signals.

All calculations implement the immutable controls in ``docs/RISK_SPEC.md``.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.models import SymbolInfo
from scanner.models import Direction

logger = get_logger("risk.engine")


@dataclass
class DailySession:
    """Track read-only daily risk status supplied by the scan loop."""

    date: date
    trades_taken: int = 0
    realized_pnl: Decimal = field(default_factory=lambda: Decimal(0))
    open_positions_count: int = 0
    is_halted: bool = False
    halt_reason: str | None = None

    def halt(self, reason: str) -> None:
        """Irreversibly record a daily halt reason for the owning scan loop."""
        self.is_halted = True
        self.halt_reason = reason


@dataclass(frozen=True)
class RiskCalculation:
    """Retain all Decimal values calculated for one viable trade candidate."""

    symbol: str
    direction: Direction
    entry_price: Decimal
    stop_price: Decimal
    take_profit: Decimal
    qty: Decimal
    position_size_usdt: Decimal
    risk_distance_pct: Decimal
    fee_cost_usd: Decimal
    slippage_cost_usd: Decimal
    effective_risk_usd: Decimal
    rr_ratio: Decimal


@dataclass(frozen=True)
class RiskDecision:
    """Describe an approval outcome without raising to a trading caller."""

    approved: bool
    reason: str
    calculation: RiskCalculation | None = None


class RiskEngine:
    """Compute Decimal position sizes and enforce immutable daily risk controls."""

    def __init__(self, config: ScannerConfig) -> None:
        """Read approved risk constants once from their confirmed config fields."""
        self._risk_usd = Decimal(str(config.risk_per_trade_usd))
        self._fee_rate = Decimal(str(config.taker_fee_rate))
        self._slippage_rate = Decimal(str(config.slippage_rate))
        self._min_rr_ratio = Decimal(str(config.min_rr_ratio))
        self._daily_loss_limit = Decimal(str(config.daily_loss_limit_usd))
        self._daily_profit_lock = Decimal(str(config.daily_profit_lock_usd))
        self._max_trades_per_day = config.max_trades_per_day

    def approve(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit: Decimal,
        direction: Direction,
        symbol_info: SymbolInfo,
        daily_session: DailySession,
    ) -> RiskDecision:
        """Run daily, geometry, sizing, and viability checks without raising."""
        try:
            daily_decision = self.check_daily_limits(daily_session)
            if not daily_decision.approved:
                self._log_rejected(symbol_info.symbol, daily_decision.reason)
                return daily_decision
            geometry_decision = self._validate_price_geometry(
                entry_price, stop_price, take_profit, direction
            )
            if geometry_decision is not None:
                self._log_rejected(symbol_info.symbol, geometry_decision.reason)
                return geometry_decision
            calculation_decision = self.calculate(
                entry_price, stop_price, take_profit, direction, symbol_info
            )
            if not calculation_decision.approved:
                self._log_rejected(symbol_info.symbol, calculation_decision.reason)
                return calculation_decision
            calculation = calculation_decision.calculation
            if calculation is None:
                return self._reject(symbol_info.symbol, "risk calculation missing")
            viability_decision = self._validate_viability(calculation, symbol_info)
            if viability_decision is not None:
                self._log_rejected(symbol_info.symbol, viability_decision.reason)
                return viability_decision
            self._log_approved(calculation)
            return RiskDecision(True, "approved", calculation)
        except Exception as error:
            reason = f"risk_engine_failure: {type(error).__name__}"
            logger.error(
                "risk_engine_failure",
                symbol=symbol_info.symbol,
                exception_type=type(error).__name__,
                message=str(error),
            )
            return RiskDecision(False, reason)

    def check_daily_limits(self, session: DailySession) -> RiskDecision:
        """Return a rejection when the scan loop's daily session is unavailable."""
        if session.is_halted:
            return RiskDecision(False, session.halt_reason or "Daily session halted")
        if session.trades_taken >= self._max_trades_per_day:
            return RiskDecision(False, "Daily trade limit reached")
        if session.realized_pnl <= self._daily_loss_limit:
            return RiskDecision(False, "Daily loss limit reached")
        if session.realized_pnl >= self._daily_profit_lock:
            return RiskDecision(False, "Daily profit lock triggered")
        return RiskDecision(True, "daily limits clear")

    def calculate(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit: Decimal,
        direction: Direction,
        symbol_info: SymbolInfo,
    ) -> RiskDecision:
        """Calculate rounded prices, floor-sized quantity, fees, and slippage."""
        try:
            geometry_decision = self._validate_price_geometry(
                entry_price, stop_price, take_profit, direction
            )
            if geometry_decision is not None:
                return self._reject(symbol_info.symbol, geometry_decision.reason)
            rounded_stop, rounded_tp = self._round_trade_prices(
                stop_price, take_profit, direction, symbol_info.tick_size
            )
            rounded_geometry = self._validate_price_geometry(
                entry_price, rounded_stop, rounded_tp, direction
            )
            if rounded_geometry is not None:
                return self._reject(symbol_info.symbol, rounded_geometry.reason)
            if symbol_info.lot_size <= 0:
                return self._reject(symbol_info.symbol, "lot size must be positive")
            risk_distance = abs(entry_price - rounded_stop)
            risk_distance_pct = risk_distance / entry_price
            position_size_usdt = self._risk_usd / risk_distance_pct
            raw_qty = position_size_usdt / entry_price
            qty = self._floor_to_increment(raw_qty, symbol_info.lot_size)
            if qty < symbol_info.min_order_qty:
                return self._reject(symbol_info.symbol, "position size below minimum")
            exit_notional = qty * rounded_tp
            fee_cost = (
                qty * entry_price * self._fee_rate + exit_notional * self._fee_rate
            )
            slippage_cost = (
                qty * entry_price * self._slippage_rate
                + exit_notional * self._slippage_rate
            )
            effective_risk = self._risk_usd + fee_cost + slippage_cost
            if effective_risk > self._risk_usd * Decimal("1.5"):
                logger.warning(
                    "effective_risk_wide",
                    symbol=symbol_info.symbol,
                    effective_risk_usd=str(effective_risk),
                    risk_usd=str(self._risk_usd),
                )
            rr_ratio = abs(entry_price - rounded_tp) / risk_distance
            calculation = RiskCalculation(
                symbol=symbol_info.symbol,
                direction=direction,
                entry_price=entry_price,
                stop_price=rounded_stop,
                take_profit=rounded_tp,
                qty=qty,
                position_size_usdt=position_size_usdt,
                risk_distance_pct=risk_distance_pct,
                fee_cost_usd=fee_cost,
                slippage_cost_usd=slippage_cost,
                effective_risk_usd=effective_risk,
                rr_ratio=rr_ratio,
            )
            return RiskDecision(True, "calculated", calculation)
        except Exception as error:
            logger.error(
                "risk_engine_failure",
                symbol=symbol_info.symbol,
                exception_type=type(error).__name__,
                message=str(error),
            )
            return RiskDecision(False, f"risk_engine_failure: {type(error).__name__}")

    @staticmethod
    def _round_price(price: Decimal, tick_size: Decimal, direction: str) -> Decimal:
        """Round price to a positive tick grid in the requested direction."""
        if tick_size <= 0:
            raise ValueError("tick size must be positive")
        ticks = price / tick_size
        rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
        return ticks.to_integral_value(rounding=rounding) * tick_size

    @staticmethod
    def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
        """Floor a non-negative Decimal to an exchange lot-size increment."""
        return (value / increment).to_integral_value(rounding=ROUND_FLOOR) * increment

    def _round_trade_prices(
        self,
        stop_price: Decimal,
        take_profit: Decimal,
        direction: Direction,
        tick_size: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Apply CTO-approved conservative stop and take-profit rounding."""
        if direction is Direction.SHORT:
            return (
                self._round_price(stop_price, tick_size, "up"),
                self._round_price(take_profit, tick_size, "up"),
            )
        return (
            self._round_price(stop_price, tick_size, "down"),
            self._round_price(take_profit, tick_size, "down"),
        )

    @staticmethod
    def _validate_price_geometry(
        entry: Decimal, stop: Decimal, tp: Decimal, direction: Direction
    ) -> RiskDecision | None:
        """Reject non-positive prices and prices on the wrong directional side."""
        if entry <= 0 or stop <= 0 or tp <= 0:
            return RiskDecision(False, "entry, stop, and take profit must be positive")
        if entry == stop:
            return RiskDecision(False, "risk distance must be positive")
        if direction is Direction.SHORT:
            if stop <= entry:
                return RiskDecision(False, "short stop must be above entry")
            if tp >= entry:
                return RiskDecision(False, "short take profit must be below entry")
        else:
            if stop >= entry:
                return RiskDecision(False, "long stop must be below entry")
            if tp <= entry:
                return RiskDecision(False, "long take profit must be above entry")
        return None

    def _validate_viability(
        self, calculation: RiskCalculation, symbol_info: SymbolInfo
    ) -> RiskDecision | None:
        """Reject any post-rounding calculation that breaches hard risk limits."""
        if calculation.qty < symbol_info.min_order_qty:
            return RiskDecision(False, "position size below minimum")
        if calculation.rr_ratio < self._min_rr_ratio:
            return RiskDecision(False, "reward-to-risk ratio below minimum")
        if calculation.effective_risk_usd > self._risk_usd * Decimal("1.5"):
            return RiskDecision(False, "effective risk exceeds hard cap")
        geometry_decision = self._validate_price_geometry(
            calculation.entry_price,
            calculation.stop_price,
            calculation.take_profit,
            calculation.direction,
        )
        return geometry_decision

    @staticmethod
    def _log_rejected(symbol: str, reason: str) -> None:
        """Emit a complete rejection audit entry without Decimal conversion risk."""
        logger.info("risk_rejected", symbol=symbol, reason=reason)

    @staticmethod
    def _reject(symbol: str, reason: str) -> RiskDecision:
        """Log and return one declined decision from the calculation boundary."""
        RiskEngine._log_rejected(symbol, reason)
        return RiskDecision(False, reason)

    @staticmethod
    def _log_approved(calculation: RiskCalculation) -> None:
        """Log an approved calculation with all Decimal fields serialized to text."""
        logger.info(
            "risk_approved",
            symbol=calculation.symbol,
            qty=str(calculation.qty),
            entry=str(calculation.entry_price),
            stop=str(calculation.stop_price),
            tp=str(calculation.take_profit),
            rr_ratio=str(calculation.rr_ratio),
            effective_risk_usd=str(calculation.effective_risk_usd),
        )
