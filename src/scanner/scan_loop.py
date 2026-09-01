"""Async orchestration of the closed-candle A+ paper-trading pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, AsyncContextManager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from scanner.candle_store.candle_store import CandleStore
from scanner.candle_store.universe_manager import UniverseManager
from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.market_data.bybit_rest import BybitRESTClient
from scanner.market_data.bybit_ws import BybitWebSocketClient
from scanner.market_data.models import SymbolInfo
from scanner.models import Candle, Direction, Regime, SignalState
from scanner.regime.detector import RegimeDetector
from scanner.risk.risk_engine import DailySession, RiskCalculation, RiskEngine
from scanner.strategy.signal_manager import SignalManager

if TYPE_CHECKING:
    from scanner.strategy.signal_manager import ActiveSignal

logger = get_logger("scan_loop")

_ONE_DAY_SECONDS = 24 * 60 * 60


class ScanLoop:
    """Orchestrate closed candles from regime refresh through paper outcomes.

    The composition root provides a CandleStore configured with this instance's
    ``_process_candle`` callback, so storage completes before orchestration.
    """

    def __init__(
        self,
        config: ScannerConfig,
        candle_store: CandleStore,
        universe_manager: UniverseManager,
        ws_client: BybitWebSocketClient,
        rest_client: BybitRESTClient,
        regime_detector: RegimeDetector,
        signal_manager: SignalManager,
        risk_engine: RiskEngine,
        session_factory: Callable[[], AsyncContextManager[AsyncSession]],
    ) -> None:
        """Create the orchestrator from its approved data and strategy components."""
        self._config = config
        self._candle_store = candle_store
        self._universe_manager = universe_manager
        self._ws_client = ws_client
        self._rest_client = rest_client
        self._regime_detector = regime_detector
        self._signal_manager = signal_manager
        self._risk_engine = risk_engine
        self._session_factory = session_factory
        self._regime = Regime.UNDEFINED
        self._daily_session = DailySession(date=datetime.now(UTC).date())
        self._symbol_info_cache: dict[str, SymbolInfo] = {}
        self._risk_calculations: dict[UUID, RiskCalculation] = {}
        self._known_symbols: set[str] = set()
        self._stop_requested = False
        self._shutdown_event = asyncio.Event()

    @property
    def daily_session(self) -> DailySession:
        """Return the current UTC-day risk session."""
        return self._daily_session

    async def run(self) -> None:
        """Initialize data, then run the store's stream until shutdown."""
        self._stop_requested = False
        self._shutdown_event.clear()
        await self._refresh_universe_and_symbol_info(initial=True)
        self._refresh_regime()
        logger.info(
            "scan_loop_started",
            universe_size=len(self._known_symbols),
            initial_regime=self._regime.value,
        )
        stream_task = asyncio.create_task(self._candle_store.run_forever())
        try:
            while not self._stop_requested:
                await asyncio.sleep(0)
                if stream_task.done():
                    await stream_task
                    return
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=_ONE_DAY_SECONDS
                    )
                except TimeoutError:
                    await self._refresh_universe_and_symbol_info(initial=False)
        finally:
            await self._candle_store.stop()
            if not stream_task.done():
                await stream_task

    async def shutdown(self) -> None:
        """Request a clean stop after the active candle callback returns."""
        self._stop_requested = True
        self._shutdown_event.set()

    async def _process_candle(self, candle: Candle) -> None:
        """Process one stored, confirmed candle in the contract's mandated order."""
        if not candle.is_closed:
            return
        self._get_or_reset_daily_session(candle.open_time.date())
        if self._is_4h_btc_close(candle):
            self._refresh_regime()
        if candle.timeframe != "60":
            return
        await self._promote_triggered_signals(candle)
        await self._check_active_signals(candle)
        if self._daily_session.is_halted:
            return
        candles_1h = self._candle_store.get_closed_candles(candle.symbol, "60", 200)
        try:
            await self._signal_manager.on_candle(candle, self._regime, candles_1h)
        except Exception as error:
            logger.error(
                "signal_manager_error",
                symbol=candle.symbol,
                exception_type=type(error).__name__,
                message=str(error),
            )
            return
        await self._handle_triggered(candle)
        logger.debug(
            "candle_processed",
            symbol=candle.symbol,
            open_time=candle.open_time.isoformat(),
        )

    async def _promote_triggered_signals(self, candle: Candle) -> None:
        """Confirm next-candle-open entries for eligible triggered signals."""
        if candle.open <= 0:
            logger.error(
                "risk_engine_error",
                symbol=candle.symbol,
                exception_type="InvalidEntryPrice",
            )
            return
        for signal in self._signals_for(candle.symbol, SignalState.TRIGGERED):
            if signal.triggered_at is None or signal.triggered_at >= candle.open_time:
                continue
            await self._signal_manager.mark_active(signal.signal_id, candle.open)
            logger.info(
                "signal_entry_confirmed",
                signal_id=str(signal.signal_id),
                symbol=signal.symbol,
                confirmed_entry=str(candle.open),
            )

    async def _handle_triggered(self, candle: Candle) -> None:
        """Obtain an approved risk calculation for this candle's new triggers."""
        for signal in self._signals_for(candle.symbol, SignalState.TRIGGERED):
            if signal.triggered_at != candle.open_time:
                continue
            symbol_info = self._symbol_info_cache.get(candle.symbol)
            if symbol_info is None:
                logger.warning("symbol_info_unavailable", symbol=candle.symbol)
                await self._signal_manager.cancel(
                    signal.signal_id, "symbol information unavailable"
                )
                continue
            if (
                signal.estimated_entry is None
                or signal.stop_price is None
                or signal.take_profit is None
            ):
                await self._signal_manager.cancel(
                    signal.signal_id, "triggered signal is missing risk prices"
                )
                continue
            try:
                decision = self._risk_engine.approve(
                    signal.estimated_entry,
                    signal.stop_price,
                    signal.take_profit,
                    signal.direction,
                    symbol_info,
                    self._daily_session,
                )
            except Exception as error:
                logger.error(
                    "risk_engine_error",
                    symbol=candle.symbol,
                    exception_type=type(error).__name__,
                )
                await self._signal_manager.cancel(signal.signal_id, "risk engine error")
                continue
            if not decision.approved or decision.calculation is None:
                logger.info(
                    "risk_rejected",
                    signal_id=str(signal.signal_id),
                    symbol=signal.symbol,
                    reason=decision.reason,
                )
                await self._signal_manager.cancel(signal.signal_id, decision.reason)
                continue
            self._risk_calculations[signal.signal_id] = decision.calculation
            logger.info(
                "risk_approved_awaiting_entry",
                signal_id=str(signal.signal_id),
                symbol=signal.symbol,
                estimated_entry=str(signal.estimated_entry),
                stop=str(signal.stop_price),
                tp=str(signal.take_profit),
            )

    async def _check_active_signals(self, candle: Candle) -> None:
        """Close active same-symbol signals when their stop or target is reached."""
        signals = self._signals_for(candle.symbol, SignalState.ACTIVE)
        if len(signals) > 1:
            logger.error(
                "multiple_active_signals", symbol=candle.symbol, count=len(signals)
            )
        for signal in signals:
            calculation = self._risk_calculations.get(signal.signal_id)
            if calculation is None or signal.estimated_entry is None:
                logger.error(
                    "risk_engine_error",
                    symbol=signal.symbol,
                    exception_type="MissingRiskCalculation",
                )
                await self._signal_manager.mark_terminal(
                    signal.signal_id,
                    SignalState.CANCELLED,
                    "missing approved risk calculation",
                )
                continue
            if signal.direction is Direction.LONG:
                sl_hit = candle.low <= calculation.stop_price
                tp_hit = candle.high >= calculation.take_profit
            else:
                sl_hit = candle.high >= calculation.stop_price
                tp_hit = candle.low <= calculation.take_profit
            if not sl_hit and not tp_hit:
                continue
            terminal_state = SignalState.SL_HIT if sl_hit else SignalState.TP_HIT
            net_pnl = self._net_pnl(signal, terminal_state)
            self._daily_session.realized_pnl += net_pnl
            self._daily_session.trades_taken += 1
            await self._signal_manager.mark_terminal(
                signal.signal_id,
                terminal_state,
                (
                    "stop loss reached"
                    if terminal_state is SignalState.SL_HIT
                    else "target reached"
                ),
            )
            self._risk_calculations.pop(signal.signal_id, None)
            event = (
                "position_closed_sl"
                if terminal_state is SignalState.SL_HIT
                else "position_closed_tp"
            )
            logger.info(
                event,
                signal_id=str(signal.signal_id),
                symbol=signal.symbol,
                net_pnl=str(net_pnl),
                daily_pnl=str(self._daily_session.realized_pnl),
            )
            self._halt_session_if_needed()

    def _net_pnl(self, signal: ActiveSignal, terminal_state: SignalState) -> Decimal:
        """Return conservative net PnL using the approved stored position quantity."""
        calculation = self._risk_calculations.get(signal.signal_id)
        if calculation is None or signal.estimated_entry is None:
            raise ValueError("active signal has no approved risk calculation")
        exit_price = (
            calculation.take_profit
            if terminal_state is SignalState.TP_HIT
            else calculation.stop_price
        )
        per_unit = (
            exit_price - signal.estimated_entry
            if signal.direction is Direction.LONG
            else signal.estimated_entry - exit_price
        )
        gross_pnl = per_unit * calculation.qty
        fee_rate = Decimal(str(self._config.taker_fee_rate))
        slippage_rate = Decimal(str(self._config.slippage_rate))
        fee_cost = calculation.qty * exit_price * fee_rate * Decimal(2)
        slippage_cost = calculation.qty * exit_price * slippage_rate * Decimal(2)
        return gross_pnl - fee_cost - slippage_cost

    def _get_or_reset_daily_session(
        self, candle_date: date | None = None
    ) -> DailySession:
        """Reset the in-memory risk session when the observed UTC date changes."""
        session_date = candle_date or datetime.now(UTC).date()
        if self._daily_session.date != session_date:
            self._daily_session = DailySession(date=session_date)
            logger.info("daily_session_reset", date=session_date.isoformat())
        return self._daily_session

    def _is_4h_btc_close(self, candle: Candle) -> bool:
        """Return whether a closed BTC candle falls on the approved 4H boundary."""
        return (
            candle.symbol == "BTCUSDT"
            and candle.open_time.hour % 4 == 0
            and candle.open_time.minute == 0
        )

    def _refresh_regime(self) -> None:
        """Refresh cached BTC regime, failing safe to UNDEFINED on any error."""
        try:
            self._regime = self._regime_detector.classify()
            logger.info(
                "regime_updated", regime=self._regime.value, change_24h_pct=None
            )
        except Exception as error:
            self._regime = Regime.UNDEFINED
            logger.error(
                "regime_refresh_failed",
                exception_type=type(error).__name__,
                message=str(error),
            )

    async def _refresh_universe_and_symbol_info(self, initial: bool) -> None:
        """Refresh eligible symbols and their metadata, subscribing only new symbols."""
        await self._universe_manager.refresh()
        symbols = self._universe_manager.symbols
        try:
            instrument_infos = await self._rest_client.get_instruments_info()
        except Exception as error:
            logger.warning(
                "symbol_info_unavailable",
                symbol="universe",
                exception_type=type(error).__name__,
            )
            instrument_infos = []
        self._symbol_info_cache = {info.symbol: info for info in instrument_infos}
        symbol_set = set(symbols)
        if initial:
            await self._candle_store.initialize(symbols, ["60"])
            await self._candle_store.initialize(["BTCUSDT"], ["240"])
        else:
            new_symbols = sorted(symbol_set - self._known_symbols)
            if new_symbols:
                await self._candle_store.initialize(new_symbols, ["60"])
        self._known_symbols.update(symbol_set)

    def _halt_session_if_needed(self) -> None:
        """Halt immediately when a terminal outcome reaches a daily limit."""
        decision = self._risk_engine.check_daily_limits(self._daily_session)
        if decision.approved:
            return
        self._daily_session.halt(decision.reason)
        logger.info(
            "daily_session_halted",
            reason=decision.reason,
            realized_pnl=str(self._daily_session.realized_pnl),
            trades_taken=self._daily_session.trades_taken,
        )

    def _signals_for(self, symbol: str, state: SignalState) -> list[ActiveSignal]:
        """Return state-filtered same-symbol snapshots from the signal manager."""
        return [
            signal
            for signal in self._signal_manager.active_signals
            if signal.symbol == symbol and signal.state is state
        ]
