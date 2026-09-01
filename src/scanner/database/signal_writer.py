"""Persistence helpers for signal lifecycle records.

Signal lifecycle rules are defined in ``docs/STRATEGY_SPEC.md`` section 6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from scanner.database.models import Signal, StateTransition
from scanner.models import SignalState

if TYPE_CHECKING:
    from scanner.strategy.signal_manager import ActiveSignal


_VALID_TRANSITIONS: dict[SignalState, frozenset[SignalState]] = {
    SignalState.DETECTED: frozenset({SignalState.WATCHING}),
    SignalState.WATCHING: frozenset(
        {SignalState.ARMED, SignalState.EXPIRED, SignalState.CANCELLED}
    ),
    SignalState.ARMED: frozenset(
        {SignalState.TRIGGERED, SignalState.EXPIRED, SignalState.CANCELLED}
    ),
    SignalState.TRIGGERED: frozenset(
        {SignalState.ACTIVE, SignalState.EXPIRED, SignalState.CANCELLED}
    ),
    SignalState.ACTIVE: frozenset(
        {SignalState.TP_HIT, SignalState.SL_HIT, SignalState.CANCELLED}
    ),
}


class SignalWriter:
    """Write signal rows and immutable lifecycle transitions without committing."""

    async def create_signal(self, session: AsyncSession, signal: ActiveSignal) -> None:
        """Insert DETECTED and its required immediate WATCHING transition.

        The caller supplies the post-transition in-memory object; the initial
        ORM record is nevertheless retained as DETECTED before its transition
        record advances the persisted state to WATCHING.
        """
        session.add(
            Signal(
                id=str(signal.signal_id),
                symbol=signal.symbol,
                direction=signal.direction.value,
                state=SignalState.DETECTED.value,
                detected_at=signal.detected_at,
                entry_price=None,
                stop_price=None,
                tp_price=None,
                score=None,
                expiration_time=signal.detected_at + timedelta(hours=4),
            )
        )
        await self.write_transition(
            session,
            signal,
            SignalState.DETECTED,
            SignalState.WATCHING,
            "initial conditions confirmed",
        )

    async def write_transition(
        self,
        session: AsyncSession,
        signal: ActiveSignal,
        from_state: SignalState,
        to_state: SignalState,
        reason: str,
    ) -> None:
        """Insert one valid transition and synchronize the current signal row.

        A TRIGGERED signal may be cancelled because STRATEGY_SPEC section 10
        makes regime changes and invalidation events cancellation conditions in
        every setup phase.
        """
        if to_state not in _VALID_TRANSITIONS.get(from_state, frozenset()):
            raise ValueError(
                f"invalid signal transition: {from_state.value} -> {to_state.value}"
            )

        session.add(
            StateTransition(
                signal_id=str(signal.signal_id),
                from_state=from_state.value,
                to_state=to_state.value,
                reason=reason,
                timestamp=datetime.now(UTC),
            )
        )
        values: dict[str, object] = {"state": to_state.value}
        if signal.estimated_entry is not None:
            values["entry_price"] = signal.estimated_entry
        if signal.stop_price is not None:
            values["stop_price"] = signal.stop_price
        if signal.take_profit is not None:
            values["tp_price"] = signal.take_profit
        if signal.score is not None:
            values["score"] = signal.score
        await session.execute(
            update(Signal).where(Signal.id == str(signal.signal_id)).values(**values)
        )
