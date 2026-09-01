"""Async DB writer for paper trade open and close events.

Writes to the existing ``Trade`` model (database/models.py) without
modifying it.  All methods run inside a caller-supplied ``AsyncSession``
so the caller controls transaction boundaries.

Ref: TASK-015 -- Paper Trading Infrastructure
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from scanner.database.models import Trade
from scanner.logging_setup import get_logger

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from scanner.risk.risk_engine import RiskCalculation
    from scanner.strategy.signal_manager import ActiveSignal

logger = get_logger("database.trade_writer")


class TradeWriter:
    """Persist paper trade lifecycle events to the ``trades`` table."""

    async def open_trade(
        self,
        session: "AsyncSession",
        signal: "ActiveSignal",
        calculation: "RiskCalculation",
        confirmed_entry: Decimal,
        opened_at: datetime,
    ) -> Trade:
        """Insert an open Trade row (exit_price and pnl_usd are None until closed)."""
        trade = Trade(
            id=str(uuid4()),
            signal_id=str(signal.signal_id),
            direction=signal.direction.value,
            qty=calculation.qty,
            entry_price=confirmed_entry,
            exit_price=None,
            pnl_usd=None,
            fee_usd=calculation.fee_cost_usd,
            slippage_usd=calculation.slippage_cost_usd,
            opened_at=opened_at,
            closed_at=None,
        )
        session.add(trade)
        await session.flush()
        logger.info(
            "trade_opened",
            trade_id=trade.id,
            signal_id=str(signal.signal_id),
            symbol=signal.symbol,
            direction=signal.direction.value,
            qty=str(calculation.qty),
            entry_price=str(confirmed_entry),
        )
        return trade

    async def close_trade(
        self,
        session: "AsyncSession",
        trade_id: str,
        exit_price: Decimal,
        pnl_usd: Decimal,
        closed_at: datetime | None = None,
    ) -> None:
        """Update an open Trade row with the final exit price and net PnL."""
        result = await session.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalar_one_or_none()
        if trade is None:
            logger.error("trade_close_not_found", trade_id=trade_id)
            return
        trade.exit_price = exit_price
        trade.pnl_usd = pnl_usd
        trade.closed_at = closed_at or datetime.now(UTC)
        await session.flush()
        outcome = "win" if pnl_usd >= Decimal("0") else "loss"
        logger.info(
            "trade_closed",
            trade_id=trade_id,
            exit_price=str(exit_price),
            pnl_usd=str(pnl_usd),
            outcome=outcome,
        )
