"""Unit tests for TradeWriter open/close lifecycle.

Ref: TASK-015
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from scanner.database.models import Trade
from scanner.database.trade_writer import TradeWriter
from scanner.models import Direction, SignalState


def _signal(symbol: str = "SOLTEST") -> MagicMock:
    sig = MagicMock()
    sig.signal_id = uuid4()
    sig.symbol = symbol
    sig.direction = Direction.SHORT
    return sig


def _calculation() -> MagicMock:
    calc = MagicMock()
    calc.qty = Decimal("2.5")
    calc.fee_cost_usd = Decimal("0.27")
    calc.slippage_cost_usd = Decimal("0.25")
    return calc


@pytest.mark.asyncio
async def test_open_trade_inserts_row_with_no_exit() -> None:
    """open_trade adds a Trade to the session with exit_price and pnl_usd as None."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    writer = TradeWriter()
    trade = await writer.open_trade(
        session,
        _signal(),
        _calculation(),
        Decimal("131.5"),
        datetime.now(UTC),
    )

    session.add.assert_called_once()
    assert isinstance(trade, Trade)
    assert trade.exit_price is None
    assert trade.pnl_usd is None
    assert trade.entry_price == Decimal("131.5")
    assert trade.qty == Decimal("2.5")


@pytest.mark.asyncio
async def test_close_trade_updates_exit_and_pnl() -> None:
    """close_trade updates exit_price, pnl_usd, and closed_at on the found row."""
    existing = Trade(
        id="trade-abc",
        signal_id=str(uuid4()),
        direction="SHORT",
        qty=Decimal("2.5"),
        entry_price=Decimal("131.5"),
        exit_price=None,
        pnl_usd=None,
        fee_usd=Decimal("0.27"),
        slippage_usd=Decimal("0.25"),
        opened_at=datetime.now(UTC),
        closed_at=None,
    )

    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=existing)

    session = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.flush = AsyncMock()

    writer = TradeWriter()
    await writer.close_trade(
        session,
        "trade-abc",
        Decimal("122.39"),
        Decimal("8.52"),
        datetime.now(UTC),
    )

    assert existing.exit_price == Decimal("122.39")
    assert existing.pnl_usd == Decimal("8.52")
    assert existing.closed_at is not None


@pytest.mark.asyncio
async def test_close_trade_noop_when_not_found() -> None:
    """close_trade logs an error and returns without raising when row is missing."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=None)

    session = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.flush = AsyncMock()

    writer = TradeWriter()
    # Should not raise
    await writer.close_trade(session, "missing-id", Decimal("100"), Decimal("0"))
    session.flush.assert_not_called()
