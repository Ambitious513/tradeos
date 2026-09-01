"""Look-ahead-safe historical replay of the approved scanner modules.

The replay engine is defined by ``tasks/active/TASK_014_BACKTEST_ENGINE.md``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import AsyncContextManager, TypedDict, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.models import SymbolInfo
from scanner.models import Candle, Direction, Regime, SignalState
from scanner.regime.detector import RegimeDetector
from scanner.risk.risk_engine import DailySession, RiskCalculation, RiskEngine
from scanner.strategy.signal_manager import ActiveSignal, SignalManager

logger = get_logger("backtest")

_ZERO = Decimal(0)
_HOURS_PER_BTC_CANDLE = 4
_BTC_CANDLE_DURATION = timedelta(hours=_HOURS_PER_BTC_CANDLE)


class _Metrics(TypedDict):
    """Type the complete Decimal and count metric set returned by the engine."""

    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    avg_win_pnl: Decimal
    avg_loss_pnl: Decimal
    profit_factor: Decimal
    expectancy: Decimal
    avg_r: Decimal
    max_drawdown: Decimal
    sharpe_ratio: Decimal
    total_net_pnl: Decimal


@dataclass(frozen=True)
class TradeRecord:
    """Immutable record of one completed paper trade in the backtest."""

    signal_id: UUID
    symbol: str
    direction: Direction
    regime_at_detection: Regime
    score: int
    entry_candle_time: datetime
    entry_price: Decimal
    stop_price: Decimal
    take_profit: Decimal
    exit_candle_time: datetime
    exit_price: Decimal
    outcome: SignalState
    qty: Decimal
    rr_ratio: Decimal
    gross_pnl: Decimal
    fee_cost: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class BacktestResult:
    """Aggregate performance summary for one symbol's backtest window."""

    symbol: str
    start_time: datetime
    end_time: datetime
    total_candles_processed: int
    total_signals_detected: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    avg_win_pnl: Decimal
    avg_loss_pnl: Decimal
    profit_factor: Decimal
    expectancy: Decimal
    avg_r: Decimal
    max_drawdown: Decimal
    sharpe_ratio: Decimal
    total_net_pnl: Decimal
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    trades: tuple[TradeRecord, ...]


class _BacktestBuffer:
    """Enforce sequential candle access with no future-candle visibility."""

    def __init__(self, max_size: int = 200) -> None:
        """Create an initially empty buffer with a positive bounded capacity."""
        if max_size < 1:
            raise ValueError("max_size must be at least one")
        self._candles: deque[Candle] = deque(maxlen=max_size)
        self._last_open_time: datetime | None = None

    def advance(self, candle: Candle) -> None:
        """Reveal one later candle, rejecting attempts to rewind the sequence."""
        if (
            self._last_open_time is not None
            and candle.open_time <= self._last_open_time
        ):
            raise ValueError("candles must be advanced in strictly increasing order")
        self._candles.append(candle)
        self._last_open_time = candle.open_time

    def get(self, n: int) -> list[Candle]:
        """Return up to ``n`` newest revealed candles in chronological order."""
        if n <= 0:
            return []
        return list(self._candles)[-n:]

    def __len__(self) -> int:
        """Return the current count of revealed candles."""
        return len(self._candles)


class _BacktestCandleStore:
    """Expose a buffer through the minimal CandleProvider read interface."""

    def __init__(self, buffer: _BacktestBuffer) -> None:
        """Bind one single-symbol, chronological buffer to the provider."""
        self._buffer = buffer

    def get_closed_candles(self, symbol: str, interval: str, n: int) -> list[Candle]:
        """Return only revealed candles; future access is structurally impossible."""
        del symbol, interval
        return self._buffer.get(n)


class _NullAsyncSession:
    """Drop-in async session that absorbs SQLAlchemy writes during backtests."""

    def add(self, *args: object, **kwargs: object) -> None:
        """Absorb SQLAlchemy's synchronous pending-object registration."""
        del args, kwargs

    async def flush(self, *args: object, **kwargs: object) -> None:
        """Absorb an asynchronous ORM flush."""
        del args, kwargs

    async def commit(self) -> None:
        """Absorb a transaction commit without writing any database rows."""

    async def rollback(self) -> None:
        """Absorb a transaction rollback without writing any database rows."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        """Absorb SQLAlchemy update execution during signal persistence."""
        del args, kwargs


@asynccontextmanager
async def _null_session_factory() -> AsyncGenerator[_NullAsyncSession, None]:
    """Yield a no-op asynchronous session for isolated backtest persistence."""
    yield _NullAsyncSession()


class BacktestEngine:
    """Replay historical candles through approved strategy modules.

    Regime classification requires at least 200 closed BTC 4H candles before it
    can produce a non-``UNDEFINED`` result. Callers should therefore supply BTC
    history extending about 33 days before the first evaluated 1H candle.
    """

    def __init__(self, config: ScannerConfig, symbol_info: SymbolInfo) -> None:
        """Construct a reusable shell; stateful components are fresh per run."""
        self._config = config
        self._symbol_info = symbol_info

    async def run(
        self,
        symbol: str,
        candles_1h: list[Candle],
        btc_candles_4h: list[Candle],
        min_warmup_candles: int = 50,
    ) -> BacktestResult:
        """Replay supplied candles sequentially, returning an empty result on error."""
        start_time = candles_1h[0].open_time if candles_1h else datetime.now(UTC)
        end_time = candles_1h[-1].open_time if candles_1h else start_time
        try:
            return await self._run_replay(
                symbol,
                candles_1h,
                btc_candles_4h,
                min_warmup_candles,
            )
        except Exception as error:
            logger.error(
                "backtest_engine_failure",
                symbol=symbol,
                exception_type=type(error).__name__,
                message=str(error),
            )
            return self._empty_result(symbol, start_time, end_time, len(candles_1h))

    async def _run_replay(
        self,
        symbol: str,
        candles_1h: list[Candle],
        btc_candles_4h: list[Candle],
        min_warmup_candles: int,
    ) -> BacktestResult:
        """Execute the mandated reveal, evaluate, then next-open-fill sequence."""
        if min_warmup_candles < 0:
            raise ValueError("min_warmup_candles cannot be negative")
        if not candles_1h:
            now = datetime.now(UTC)
            return self._empty_result(symbol, now, now, 0)

        sym_buffer = _BacktestBuffer(max_size=200)
        btc_buffer = _BacktestBuffer(max_size=250)
        btc_pointer = [0]
        btc_store = _BacktestCandleStore(btc_buffer)
        signal_store = _BacktestCandleStore(sym_buffer)
        regime_detector = RegimeDetector(btc_store, self._config)
        signal_manager = SignalManager(
            signal_store,
            cast(AsyncContextManagerFactory, _null_session_factory),
            self._config,
        )
        risk_engine = RiskEngine(self._config)
        regime = Regime.UNDEFINED
        daily_session = DailySession(date=candles_1h[0].open_time.date())
        risk_calculations: dict[UUID, RiskCalculation] = {}
        regimes_at_detection: dict[UUID, Regime] = {}
        trade_records: list[TradeRecord] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        signals_detected = 0

        logger.info(
            "backtest_started",
            symbol=symbol,
            total_candles=len(candles_1h),
            warmup=min_warmup_candles,
        )
        for index, candle in enumerate(candles_1h):
            if not candle.is_closed:
                continue
            sym_buffer.advance(candle)
            self._advance_btc_to(
                btc_buffer, btc_candles_4h, candle.open_time, btc_pointer
            )
            if self._is_4h_boundary(candle.open_time):
                regime = regime_detector.classify()
            if index < min_warmup_candles:
                continue

            daily_session = self._reset_session_if_needed(
                daily_session, candle.open_time.date()
            )
            await self._promote_triggered(signal_manager, risk_calculations, candle)
            await self._check_active_signals(
                signal_manager,
                risk_calculations,
                regimes_at_detection,
                candle,
                daily_session,
                trade_records,
                equity_curve,
            )
            if not daily_session.is_halted:
                await signal_manager.on_candle(candle, regime, sym_buffer.get(200))
                signals_detected += await self._handle_triggered(
                    signal_manager,
                    risk_engine,
                    risk_calculations,
                    regimes_at_detection,
                    candle,
                    daily_session,
                    regime,
                )

        result = self._result_from_records(
            symbol,
            candles_1h,
            signals_detected,
            trade_records,
            equity_curve,
        )
        logger.info(
            "backtest_completed",
            symbol=symbol,
            total_trades=result.total_trades,
            win_rate=str(result.win_rate),
            total_pnl=str(result.total_net_pnl),
        )
        return result

    @staticmethod
    def _advance_btc_to(
        btc_buffer: _BacktestBuffer,
        btc_candles: list[Candle],
        target_time: datetime,
        pointer: list[int],
    ) -> None:
        """Reveal BTC candles only after their close time has passed.

        A 4H BTC candle with open_time=T closes at T+4H.  It is not available
        in a live CandleStore before T+4H, so it must not enter the backtest
        BTC buffer until target_time reaches T+4H.
        """
        while pointer[0] < len(btc_candles):
            btc_candle = btc_candles[pointer[0]]
            candle_close_time = btc_candle.open_time + _BTC_CANDLE_DURATION
            if candle_close_time > target_time:
                return
            pointer[0] += 1
            if btc_candle.is_closed:
                btc_buffer.advance(btc_candle)

    @staticmethod
    def _is_4h_boundary(candle_time: datetime) -> bool:
        """Return whether a one-hour replay step crosses a UTC 4H boundary."""
        return candle_time.hour % _HOURS_PER_BTC_CANDLE == 0 and candle_time.minute == 0

    @staticmethod
    def _reset_session_if_needed(
        session: DailySession, candle_date: date
    ) -> DailySession:
        """Create a fresh UTC daily session at a candle-date boundary."""
        if session.date == candle_date:
            return session
        logger.info("daily_session_reset", date=candle_date.isoformat())
        return DailySession(date=candle_date)

    @staticmethod
    async def _promote_triggered(
        signal_manager: SignalManager,
        risk_calculations: dict[UUID, RiskCalculation],
        candle: Candle,
    ) -> None:
        """Open prior triggers at this revealed candle's open, never its close."""
        for signal in BacktestEngine._signals_for(
            signal_manager, candle.symbol, SignalState.TRIGGERED
        ):
            if signal.triggered_at is None or signal.triggered_at >= candle.open_time:
                continue
            if signal.signal_id not in risk_calculations:
                logger.warning("signal_no_risk_calc", signal_id=str(signal.signal_id))
                await signal_manager.cancel(
                    signal.signal_id, "missing risk calculation"
                )
                continue
            await signal_manager.mark_active(signal.signal_id, candle.open)

    async def _check_active_signals(
        self,
        signal_manager: SignalManager,
        risk_calculations: dict[UUID, RiskCalculation],
        regimes_at_detection: dict[UUID, Regime],
        candle: Candle,
        daily_session: DailySession,
        trade_records: list[TradeRecord],
        equity_curve: list[tuple[datetime, Decimal]],
    ) -> None:
        """Close active positions from high/low data, with SL winning ties."""
        for signal in self._signals_for(
            signal_manager, candle.symbol, SignalState.ACTIVE
        ):
            calculation = risk_calculations.get(signal.signal_id)
            if calculation is None or signal.estimated_entry is None:
                logger.warning("signal_no_risk_calc", signal_id=str(signal.signal_id))
                continue
            if signal.direction is Direction.LONG:
                sl_hit = candle.low <= calculation.stop_price
                tp_hit = candle.high >= calculation.take_profit
            else:
                sl_hit = candle.high >= calculation.stop_price
                tp_hit = candle.low <= calculation.take_profit
            if not sl_hit and not tp_hit:
                continue
            outcome = SignalState.SL_HIT if sl_hit else SignalState.TP_HIT
            record = self._record_trade(
                signal,
                calculation,
                regimes_at_detection.get(signal.signal_id, Regime.UNDEFINED),
                candle,
                outcome,
            )
            trade_records.append(record)
            cumulative = (
                equity_curve[-1][1] if equity_curve else _ZERO
            ) + record.net_pnl
            equity_curve.append((candle.open_time, cumulative))
            daily_session.realized_pnl += record.net_pnl
            daily_session.trades_taken += 1
            risk_calculations.pop(signal.signal_id, None)
            regimes_at_detection.pop(signal.signal_id, None)
            await signal_manager.mark_terminal(
                signal.signal_id,
                outcome,
                (
                    "stop loss reached"
                    if outcome is SignalState.SL_HIT
                    else "target reached"
                ),
            )
            logger.info(
                "trade_recorded",
                symbol=record.symbol,
                outcome=record.outcome.value,
                net_pnl=str(record.net_pnl),
            )
            decision = RiskEngine(self._config).check_daily_limits(daily_session)
            if not decision.approved:
                daily_session.halt(decision.reason)

    async def _handle_triggered(
        self,
        signal_manager: SignalManager,
        risk_engine: RiskEngine,
        risk_calculations: dict[UUID, RiskCalculation],
        regimes_at_detection: dict[UUID, Regime],
        candle: Candle,
        daily_session: DailySession,
        regime: Regime,
    ) -> int:
        """Risk-approve exactly this candle's triggers and retain their context."""
        approved_count = 0
        for signal in self._signals_for(
            signal_manager, candle.symbol, SignalState.TRIGGERED
        ):
            if signal.triggered_at != candle.open_time:
                continue
            if (
                signal.estimated_entry is None
                or signal.stop_price is None
                or signal.take_profit is None
            ):
                await signal_manager.cancel(
                    signal.signal_id, "trigger missing risk prices"
                )
                continue
            decision = risk_engine.approve(
                signal.estimated_entry,
                signal.stop_price,
                signal.take_profit,
                signal.direction,
                self._symbol_info,
                daily_session,
            )
            if not decision.approved or decision.calculation is None:
                await signal_manager.cancel(signal.signal_id, decision.reason)
                continue
            risk_calculations[signal.signal_id] = decision.calculation
            regimes_at_detection[signal.signal_id] = regime
            approved_count += 1
        return approved_count

    def _record_trade(
        self,
        signal: ActiveSignal,
        calculation: RiskCalculation,
        regime: Regime,
        candle: Candle,
        outcome: SignalState,
    ) -> TradeRecord:
        """Calculate one completed trade's conservative Decimal-only PnL values."""
        if signal.estimated_entry is None or signal.triggered_at is None:
            raise ValueError("active signal is missing confirmed entry metadata")
        exit_price = (
            calculation.stop_price
            if outcome is SignalState.SL_HIT
            else calculation.take_profit
        )
        gross_pnl = (
            (exit_price - signal.estimated_entry) * calculation.qty
            if signal.direction is Direction.LONG
            else (signal.estimated_entry - exit_price) * calculation.qty
        )
        fee_rate = Decimal(str(self._config.taker_fee_rate))
        slippage_rate = Decimal(str(self._config.slippage_rate))
        notional = calculation.qty * (signal.estimated_entry + exit_price)
        fee_cost = notional * fee_rate
        slippage_cost = notional * slippage_rate
        return TradeRecord(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            regime_at_detection=regime,
            score=signal.score or 0,
            entry_candle_time=signal.triggered_at,
            entry_price=signal.estimated_entry,
            stop_price=calculation.stop_price,
            take_profit=calculation.take_profit,
            exit_candle_time=candle.open_time,
            exit_price=exit_price,
            outcome=outcome,
            qty=calculation.qty,
            rr_ratio=calculation.rr_ratio,
            gross_pnl=gross_pnl,
            fee_cost=fee_cost,
            slippage_cost=slippage_cost,
            net_pnl=gross_pnl - fee_cost - slippage_cost,
        )

    @staticmethod
    def _signals_for(
        signal_manager: SignalManager, symbol: str, state: SignalState
    ) -> list[ActiveSignal]:
        """Return a snapshot of one symbol's signals in the requested state."""
        return [
            signal
            for signal in signal_manager.active_signals
            if signal.symbol == symbol and signal.state is state
        ]

    def _result_from_records(
        self,
        symbol: str,
        candles: list[Candle],
        signals_detected: int,
        trades: list[TradeRecord],
        equity_curve: list[tuple[datetime, Decimal]],
    ) -> BacktestResult:
        """Build an immutable result from completed trades and replay metadata."""
        metrics = self._compute_metrics(trades, equity_curve)
        return BacktestResult(
            symbol=symbol,
            start_time=candles[0].open_time,
            end_time=candles[-1].open_time,
            total_candles_processed=len(candles),
            total_signals_detected=signals_detected,
            total_trades=len(trades),
            winning_trades=metrics["winning_trades"],
            losing_trades=metrics["losing_trades"],
            win_rate=metrics["win_rate"],
            avg_win_pnl=metrics["avg_win_pnl"],
            avg_loss_pnl=metrics["avg_loss_pnl"],
            profit_factor=metrics["profit_factor"],
            expectancy=metrics["expectancy"],
            avg_r=metrics["avg_r"],
            max_drawdown=metrics["max_drawdown"],
            sharpe_ratio=metrics["sharpe_ratio"],
            total_net_pnl=metrics["total_net_pnl"],
            equity_curve=tuple(equity_curve),
            trades=tuple(trades),
        )

    @staticmethod
    def _compute_metrics(
        trades: list[TradeRecord], equity_curve: list[tuple[datetime, Decimal]]
    ) -> _Metrics:
        """Compute Decimal-only aggregate metrics with zero-safe edge behavior."""
        if not trades:
            return {
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": _ZERO,
                "avg_win_pnl": _ZERO,
                "avg_loss_pnl": _ZERO,
                "profit_factor": _ZERO,
                "expectancy": _ZERO,
                "avg_r": _ZERO,
                "max_drawdown": _ZERO,
                "sharpe_ratio": _ZERO,
                "total_net_pnl": _ZERO,
            }
        wins = [trade.net_pnl for trade in trades if trade.net_pnl > _ZERO]
        losses = [trade.net_pnl for trade in trades if trade.net_pnl < _ZERO]
        total_net_pnl = sum((trade.net_pnl for trade in trades), start=_ZERO)
        expectancy = total_net_pnl / Decimal(len(trades))
        avg_risk = sum(
            (abs(trade.entry_price - trade.stop_price) * trade.qty for trade in trades),
            start=_ZERO,
        ) / Decimal(len(trades))
        return {
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": Decimal(len(wins)) / Decimal(len(trades)),
            "avg_win_pnl": (
                sum(wins, start=_ZERO) / Decimal(len(wins)) if wins else _ZERO
            ),
            "avg_loss_pnl": (
                sum(losses, start=_ZERO) / Decimal(len(losses)) if losses else _ZERO
            ),
            "profit_factor": (
                sum(wins, start=_ZERO) / abs(sum(losses, start=_ZERO))
                if losses
                else _ZERO
            ),
            "expectancy": expectancy,
            "avg_r": expectancy / avg_risk if avg_risk else _ZERO,
            "max_drawdown": BacktestEngine._max_drawdown(equity_curve),
            "sharpe_ratio": BacktestEngine._sharpe_ratio(trades),
            "total_net_pnl": total_net_pnl,
        }

    @staticmethod
    def _max_drawdown(equity_curve: list[tuple[datetime, Decimal]]) -> Decimal:
        """Return the non-negative peak-to-trough cumulative-equity decline."""
        peak = _ZERO
        max_drawdown = _ZERO
        for _, equity in equity_curve:
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return max_drawdown

    @staticmethod
    def _sharpe_ratio(trades: list[TradeRecord]) -> Decimal:
        """Return annualized 365-day Sharpe from UTC-date grouped trade PnL."""
        daily_pnl: dict[date, Decimal] = {}
        for trade in trades:
            day = trade.exit_candle_time.astimezone(UTC).date()
            daily_pnl[day] = daily_pnl.get(day, _ZERO) + trade.net_pnl
        values = list(daily_pnl.values())
        if len(values) < 2:
            return _ZERO
        mean = sum(values, start=_ZERO) / Decimal(len(values))
        variance = sum(
            ((value - mean) ** 2 for value in values), start=_ZERO
        ) / Decimal(len(values))
        if variance == _ZERO:
            return _ZERO
        return mean / variance.sqrt() * Decimal(365).sqrt()

    @staticmethod
    def _empty_result(
        symbol: str, start_time: datetime, end_time: datetime, candles_processed: int
    ) -> BacktestResult:
        """Return the contract's safe immutable empty result after any failure."""
        metrics = BacktestEngine._compute_metrics([], [])
        return BacktestResult(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            total_candles_processed=candles_processed,
            total_signals_detected=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=metrics["win_rate"],
            avg_win_pnl=metrics["avg_win_pnl"],
            avg_loss_pnl=metrics["avg_loss_pnl"],
            profit_factor=metrics["profit_factor"],
            expectancy=metrics["expectancy"],
            avg_r=metrics["avg_r"],
            max_drawdown=metrics["max_drawdown"],
            sharpe_ratio=metrics["sharpe_ratio"],
            total_net_pnl=metrics["total_net_pnl"],
            equity_curve=(),
            trades=(),
        )


AsyncContextManagerFactory = Callable[[], AsyncContextManager[AsyncSession]]
