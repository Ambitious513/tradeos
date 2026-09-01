"""In-memory A+ signal lifecycle management.

The irreversible lifecycle follows ``docs/STRATEGY_SPEC.md`` sections 6 and
10.  This module deliberately performs no exchange or position operations.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import AsyncContextManager, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from scanner.config import ScannerConfig
from scanner.database.signal_writer import SignalWriter
from scanner.logging_setup import get_logger
from scanner.models import TERMINAL_STATES, Candle, Direction, Regime, SignalState
from scanner.protocols import CandleProvider
from scanner.strategy.score_engine import ScoreInput, compute_score, is_a_plus
from scanner.strategy.setup_detector import (
    SetupContext,
    check_24h_level_interaction,
    check_bullish_rejection_candle,
    check_entry_trigger_long,
    check_entry_trigger_short,
    check_liquidity_sweep,
    check_minimum_rr,
    check_rejection_candle,
    check_retest_long,
    check_retest_short,
    compute_24h_stats,
    compute_avg_volume,
    compute_stop_long,
    compute_stop_short,
    compute_take_profit,
    detect_initial_conditions,
)

logger = get_logger("strategy.signal_manager")


@dataclass
class ActiveSignal:
    """Mutable in-memory representation of one non-terminal lifecycle signal."""

    signal_id: UUID
    symbol: str
    direction: Direction
    state: SignalState
    detected_at: datetime
    setup_context: SetupContext
    rejection_candle: Candle | None = None
    rejection_at: datetime | None = None
    high_24h_at_armed: Decimal | None = None
    low_24h_at_armed: Decimal | None = None
    retest_candle: Candle | None = None
    retest_at: datetime | None = None
    score: int | None = None
    estimated_entry: Decimal | None = None
    stop_price: Decimal | None = None
    take_profit: Decimal | None = None
    triggered_at: datetime | None = None


@dataclass(frozen=True)
class _CreateEvent:
    """Represent one new signal persistence request."""

    signal: ActiveSignal


@dataclass(frozen=True)
class _TransitionEvent:
    """Represent one already-applied in-memory transition to persist."""

    signal: ActiveSignal
    from_state: SignalState
    to_state: SignalState
    reason: str


_PersistenceEvent = _CreateEvent | _TransitionEvent


class SignalManager:
    """Advance live setup signals from WATCHING through terminal outcomes."""

    def __init__(
        self,
        candle_store: CandleProvider,
        session_factory: Callable[[], AsyncContextManager[AsyncSession]],
        config: ScannerConfig,
    ) -> None:
        """Create a manager using the supplied candle store and DB sessions."""
        self._candle_store = candle_store
        self._session_factory = session_factory
        self._config = config
        self._writer = SignalWriter()
        self._active_signals: list[ActiveSignal] = []

    @property
    def active_signals(self) -> list[ActiveSignal]:
        """Return a shallow copy of the non-terminal active signal list."""
        return list(self._active_signals)

    async def on_candle(
        self, candle: Candle, regime: Regime, candles_1h: list[Candle]
    ) -> None:
        """Process one newly closed 1H candle and persist its transitions."""
        if not candle.is_closed:
            logger.error(
                "candle_validation_failed",
                symbol=candle.symbol,
                field="is_closed",
                value=str(candle.is_closed),
            )
            return

        events: list[_PersistenceEvent] = []
        self._expire_or_cancel_stale(candle, regime, events)
        self._advance_armed(candle, candles_1h, events)
        self._advance_watching(candle, candles_1h, events)
        self._detect_new_signal(candle, regime, candles_1h, events)
        self._remove_terminal_signals()
        await self._persist(events)

    async def mark_active(self, signal_id: UUID, confirmed_entry: Decimal) -> None:
        """Advance a TRIGGERED signal to ACTIVE using its confirmed next-open entry."""
        signal = self._require_signal(signal_id)
        if signal.state is not SignalState.TRIGGERED:
            raise ValueError("only a TRIGGERED signal can be marked ACTIVE")
        events: list[_PersistenceEvent] = []
        signal.estimated_entry = confirmed_entry
        self._transition(
            signal,
            SignalState.ACTIVE,
            "next candle open confirmed entry",
            datetime.now(UTC),
            events,
        )
        await self._persist(events)

    async def mark_terminal(
        self, signal_id: UUID, terminal_state: SignalState, reason: str
    ) -> None:
        """Advance an ACTIVE signal to TP_HIT, SL_HIT, or CANCELLED."""
        allowed_terminal_states = {
            SignalState.TP_HIT,
            SignalState.SL_HIT,
            SignalState.CANCELLED,
        }
        if (
            terminal_state not in TERMINAL_STATES
            or terminal_state not in allowed_terminal_states
        ):
            raise ValueError("terminal state is not valid for an ACTIVE signal")
        signal = self._require_signal(signal_id)
        if signal.state is not SignalState.ACTIVE:
            raise ValueError("only an ACTIVE signal can be marked terminal")
        events: list[_PersistenceEvent] = []
        self._transition(signal, terminal_state, reason, datetime.now(UTC), events)
        self._remove_terminal_signals()
        await self._persist(events)

    async def cancel(self, signal_id: UUID, reason: str) -> None:
        """Cancel a non-terminal, pre-entry signal for a documented reason."""
        signal = self._require_signal(signal_id)
        if signal.state is SignalState.ACTIVE:
            raise ValueError("use mark_terminal() to cancel an ACTIVE signal")
        if signal.state in TERMINAL_STATES:
            raise ValueError(f"signal is already terminal: {signal.state.value}")
        events: list[_PersistenceEvent] = []
        self._transition(
            signal, SignalState.CANCELLED, reason, datetime.now(UTC), events
        )
        self._remove_terminal_signals()
        await self._persist(events)

    def _expire_or_cancel_stale(
        self,
        candle: Candle,
        regime: Regime,
        events: list[_PersistenceEvent],
    ) -> None:
        """Apply regime, level-invalidation, and phase-expiration rules first."""
        for signal in self._signals_for_symbol(candle.symbol):
            if self._regime_is_invalid(signal.direction, regime):
                self._transition(
                    signal,
                    SignalState.CANCELLED,
                    "BTC regime no longer aligns with signal direction",
                    candle.open_time,
                    events,
                )
                continue
            if self._makes_new_24h_extreme(signal, candle):
                self._transition(
                    signal,
                    SignalState.CANCELLED,
                    "new 24H directional extreme invalidated setup",
                    candle.open_time,
                    events,
                )
                continue
            if signal.state is SignalState.WATCHING and (
                candle.open_time - signal.detected_at > timedelta(hours=4)
            ):
                self._transition(
                    signal,
                    SignalState.EXPIRED,
                    "no rejection candle within four hours of detection",
                    candle.open_time,
                    events,
                )
                continue
            if signal.state is SignalState.ARMED:
                if signal.retest_at is None and signal.rejection_at is not None:
                    if candle.open_time - signal.rejection_at > timedelta(hours=4):
                        self._transition(
                            signal,
                            SignalState.EXPIRED,
                            "no retest within four hours of rejection",
                            candle.open_time,
                            events,
                        )
                elif signal.retest_at is not None and (
                    candle.open_time - signal.retest_at > timedelta(hours=4)
                ):
                    self._transition(
                        signal,
                        SignalState.EXPIRED,
                        "no entry trigger within four hours of retest",
                        candle.open_time,
                        events,
                    )
            if (
                signal.state is SignalState.TRIGGERED
                and signal.triggered_at is not None
            ):
                if candle.open_time - signal.triggered_at > timedelta(hours=1):
                    self._transition(
                        signal,
                        SignalState.EXPIRED,
                        "entry was not confirmed within one hour of trigger",
                        candle.open_time,
                        events,
                    )

    def _advance_armed(
        self,
        candle: Candle,
        candles_1h: list[Candle],
        events: list[_PersistenceEvent],
    ) -> None:
        """Record a retest or advance only a prior retest through its trigger."""
        for signal in self._signals_for_symbol(candle.symbol, SignalState.ARMED):
            rejection = signal.rejection_candle
            if rejection is None:
                logger.error(
                    "signal_transition_failed",
                    signal_id=str(signal.signal_id),
                    reason="ARMED signal is missing rejection candle",
                )
                continue
            if signal.retest_candle is None:
                if self._is_retest(signal, candle):
                    signal.retest_candle = candle
                    signal.retest_at = candle.open_time
                continue
            if not self._is_entry_trigger(signal, candle):
                continue
            self._score_and_trigger(signal, candle, candles_1h, events)

    def _advance_watching(
        self,
        candle: Candle,
        candles_1h: list[Candle],
        events: list[_PersistenceEvent],
    ) -> None:
        """Confirm a directional rejection and move WATCHING to ARMED."""
        stats = compute_24h_stats(candles_1h)
        for signal in self._signals_for_symbol(candle.symbol, SignalState.WATCHING):
            high_24h = stats[0] if stats is not None else signal.setup_context.high_24h
            low_24h = stats[1] if stats is not None else signal.setup_context.low_24h
            is_rejection = (
                check_24h_level_interaction(candle, high_24h, Direction.SHORT)
                and check_rejection_candle(candle, high_24h)
                if signal.direction is Direction.SHORT
                else check_liquidity_sweep(candle, low_24h)
                and check_bullish_rejection_candle(candle, low_24h)
            )
            if not is_rejection:
                continue
            signal.rejection_candle = candle
            signal.rejection_at = candle.open_time
            signal.high_24h_at_armed = high_24h
            signal.low_24h_at_armed = low_24h
            self._transition(
                signal,
                SignalState.ARMED,
                "directional rejection candle confirmed",
                candle.open_time,
                events,
            )

    def _detect_new_signal(
        self,
        candle: Candle,
        regime: Regime,
        candles_1h: list[Candle],
        events: list[_PersistenceEvent],
    ) -> None:
        """Create a same-cycle WATCHING signal when initial conditions hold."""
        if regime is Regime.BEARISH:
            direction = Direction.SHORT
        elif regime is Regime.BULLISH:
            direction = Direction.LONG
        else:
            return

        existing = next(
            (
                signal
                for signal in self._signals_for_symbol(candle.symbol)
                if signal.state
                in {
                    SignalState.WATCHING,
                    SignalState.ARMED,
                    SignalState.TRIGGERED,
                    SignalState.ACTIVE,
                }
            ),
            None,
        )
        if existing is not None:
            logger.warning(
                "duplicate_signal_rejected",
                symbol=candle.symbol,
                existing_state=existing.state.value,
            )
            return
        context = detect_initial_conditions(candles_1h, direction, self._config)
        if context is None:
            return
        signal = ActiveSignal(
            signal_id=uuid4(),
            symbol=context.symbol,
            direction=direction,
            state=SignalState.WATCHING,
            detected_at=context.trigger_candle.open_time,
            setup_context=context,
        )
        self._active_signals.append(signal)
        events.append(_CreateEvent(signal))
        logger.info(
            "signal_detected",
            signal_id=str(signal.signal_id),
            symbol=signal.symbol,
            direction=signal.direction.value,
            change_24h_pct=str(context.change_24h_pct),
            rsi_14=str(context.rsi_14),
            reason="initial conditions confirmed",
            transition_at=signal.detected_at.isoformat(),
        )
        logger.info(
            "signal_watching",
            signal_id=str(signal.signal_id),
            symbol=signal.symbol,
            reason="initial conditions confirmed",
            transition_at=signal.detected_at.isoformat(),
        )

    def _score_and_trigger(
        self,
        signal: ActiveSignal,
        candle: Candle,
        candles_1h: list[Candle],
        events: list[_PersistenceEvent],
    ) -> None:
        """Compute risk and A+ score once for a valid post-retest trigger."""
        rejection = signal.rejection_candle
        if rejection is None:
            return
        estimated_entry = candle.close
        if signal.direction is Direction.SHORT:
            stop_price = compute_stop_short(
                estimated_entry, candles_1h[-3:], signal.setup_context.atr_14
            )
        else:
            stop_price = compute_stop_long(
                estimated_entry, candles_1h[-3:], signal.setup_context.atr_14
            )
        take_profit = compute_take_profit(estimated_entry, stop_price, signal.direction)
        if not check_minimum_rr(
            estimated_entry,
            stop_price,
            take_profit,
            signal.direction,
            Decimal(str(self._config.min_rr_ratio)),
        ):
            self._transition(
                signal,
                SignalState.EXPIRED,
                "calculated reward-to-risk is below minimum",
                candle.open_time,
                events,
            )
            return
        score_input = ScoreInput(
            setup_context=signal.setup_context,
            rejection_candle=rejection,
            avg_volume_20=compute_avg_volume(candles_1h),
            sweep_or_excess_pct=self._sweep_or_excess_pct(signal),
            entry_price=estimated_entry,
            stop_price=stop_price,
            take_profit=take_profit,
        )
        score = compute_score(score_input)
        if not 20 <= score <= 100:
            logger.error(
                "signal_score_invalid",
                signal_id=str(signal.signal_id),
                score=score,
            )
            self._transition(
                signal,
                SignalState.EXPIRED,
                "score was outside the valid 20 to 100 range",
                candle.open_time,
                events,
            )
            return
        signal.score = score
        signal.estimated_entry = estimated_entry
        signal.stop_price = stop_price
        signal.take_profit = take_profit
        signal.triggered_at = candle.open_time
        if not is_a_plus(score):
            self._transition(
                signal,
                SignalState.EXPIRED,
                "score is below A+ threshold",
                candle.open_time,
                events,
            )
            return
        self._transition(
            signal,
            SignalState.TRIGGERED,
            "post-retest entry trigger confirmed",
            candle.open_time,
            events,
        )

    def _transition(
        self,
        signal: ActiveSignal,
        to_state: SignalState,
        reason: str,
        transition_at: datetime,
        events: list[_PersistenceEvent],
    ) -> None:
        """Apply and log one irreversible in-memory transition."""
        from_state = signal.state
        signal.state = to_state
        events.append(_TransitionEvent(signal, from_state, to_state, reason))
        fields = {
            "signal_id": str(signal.signal_id),
            "symbol": signal.symbol,
            "reason": reason,
            "transition_at": transition_at.isoformat(),
        }
        if to_state is SignalState.ARMED:
            logger.info(
                "signal_armed",
                rejection_at=(
                    signal.rejection_at.isoformat()
                    if signal.rejection_at is not None
                    else None
                ),
                **fields,
            )
        elif to_state is SignalState.TRIGGERED:
            logger.info(
                "signal_triggered",
                score=signal.score,
                estimated_entry=str(signal.estimated_entry),
                stop_price=str(signal.stop_price),
                **fields,
            )
        elif to_state is SignalState.ACTIVE:
            logger.info(
                "signal_active",
                confirmed_entry=str(signal.estimated_entry),
                **fields,
            )
        elif to_state is SignalState.EXPIRED:
            logger.info("signal_expired", state=from_state.value, **fields)
        elif to_state is SignalState.CANCELLED:
            logger.info("signal_cancelled", **fields)

    async def _persist(self, events: list[_PersistenceEvent]) -> None:
        """Write collected events through one caller-owned manager transaction."""
        if not events:
            return
        try:
            raw_context = self._session_factory()
            if inspect.isawaitable(raw_context):
                context = cast(AsyncContextManager[AsyncSession], await raw_context)
            else:
                context = raw_context
            async with context as session:
                for event in events:
                    try:
                        if isinstance(event, _CreateEvent):
                            await self._writer.create_signal(session, event.signal)
                        else:
                            await self._writer.write_transition(
                                session,
                                event.signal,
                                event.from_state,
                                event.to_state,
                                event.reason,
                            )
                    except ValueError as error:
                        logger.error(
                            "signal_transition_failed",
                            signal_id=str(event.signal.signal_id),
                            exception_type=type(error).__name__,
                            reason=str(error),
                        )
                await session.commit()
        except Exception as error:
            logger.error(
                "signal_persistence_failed",
                exception_type=type(error).__name__,
                message=str(error),
            )

    def _signals_for_symbol(
        self, symbol: str, state: SignalState | None = None
    ) -> list[ActiveSignal]:
        """Return matching non-terminal signals without exposing internal storage."""
        return [
            signal
            for signal in self._active_signals
            if signal.symbol == symbol
            and signal.state not in TERMINAL_STATES
            and (state is None or signal.state is state)
        ]

    def _require_signal(self, signal_id: UUID) -> ActiveSignal:
        """Return one tracked signal or raise a clear error for an unknown ID."""
        for signal in self._active_signals:
            if signal.signal_id == signal_id:
                return signal
        raise ValueError(f"unknown active signal: {signal_id}")

    def _remove_terminal_signals(self) -> None:
        """Retain only live signals after the current processing cycle."""
        self._active_signals = [
            signal
            for signal in self._active_signals
            if signal.state not in TERMINAL_STATES
        ]

    @staticmethod
    def _regime_is_invalid(direction: Direction, regime: Regime) -> bool:
        """Return whether BTC regime no longer supports the signal direction."""
        return (direction is Direction.SHORT and regime is not Regime.BEARISH) or (
            direction is Direction.LONG and regime is not Regime.BULLISH
        )

    @staticmethod
    def _makes_new_24h_extreme(signal: ActiveSignal, candle: Candle) -> bool:
        """Return whether a candle invalidates the stored directional level."""
        if signal.direction is Direction.SHORT:
            high_24h = signal.high_24h_at_armed or signal.setup_context.high_24h
            return candle.high > high_24h
        low_24h = signal.low_24h_at_armed or signal.setup_context.low_24h
        return candle.low < low_24h

    @staticmethod
    def _is_retest(signal: ActiveSignal, candle: Candle) -> bool:
        """Return whether this post-rejection candle satisfies its retest rule."""
        rejection = signal.rejection_candle
        if rejection is None:
            return False
        if signal.direction is Direction.SHORT:
            return check_retest_short(
                candle,
                rejection.close,
                signal.high_24h_at_armed or signal.setup_context.high_24h,
            )
        return check_retest_long(
            candle,
            rejection.close,
            signal.low_24h_at_armed or signal.setup_context.low_24h,
        )

    @staticmethod
    def _is_entry_trigger(signal: ActiveSignal, candle: Candle) -> bool:
        """Return whether a candle breaks the prior retest in the setup direction."""
        retest = signal.retest_candle
        if retest is None:
            return False
        if signal.direction is Direction.SHORT:
            return check_entry_trigger_short(candle, retest.low)
        return check_entry_trigger_long(candle, retest.high)

    @staticmethod
    def _sweep_or_excess_pct(signal: ActiveSignal) -> Decimal:
        """Compute SCORE-001's directional 24H level penetration metric."""
        rejection = signal.rejection_candle
        if rejection is None:
            return Decimal(0)
        if signal.direction is Direction.SHORT:
            high_24h = signal.high_24h_at_armed or signal.setup_context.high_24h
            if high_24h == 0:
                return Decimal(0)
            return max(
                (rejection.high - high_24h) / high_24h * Decimal(100), Decimal(0)
            )
        low_24h = signal.low_24h_at_armed or signal.setup_context.low_24h
        if low_24h == 0:
            return Decimal(0)
        return (low_24h - rejection.low) / low_24h * Decimal(100)
