"""Unit tests verifying AlertEngine + TradeWriter calls in ScanLoop lifecycle.

Ref: TASK-015
"""

from __future__ import annotations

import asyncio
import pytest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from scanner.models import Direction, Regime, SignalState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candle(symbol: str = "SOLTEST", open_: float = 131.18):
    c = MagicMock()
    c.symbol = symbol
    c.timeframe = "60"
    c.is_closed = True
    c.open = Decimal(str(open_))
    c.high = Decimal("133.0")
    c.low = Decimal("122.0")
    c.close = Decimal("122.5")
    c.open_time = datetime(2024, 6, 14, 10, 0, tzinfo=UTC)
    return c


def _signal(state: SignalState = SignalState.TRIGGERED, symbol: str = "SOLTEST"):
    sig = MagicMock()
    sig.signal_id = uuid4()
    sig.symbol = symbol
    sig.direction = Direction.SHORT
    sig.state = state
    sig.estimated_entry = Decimal("131.5")
    sig.stop_price = Decimal("136.05")
    sig.take_profit = Decimal("122.39")
    sig.triggered_at = datetime(2024, 6, 14, 9, 0, tzinfo=UTC)
    return sig


def _calculation():
    calc = MagicMock()
    calc.rr_ratio = Decimal("2.0")
    calc.qty = Decimal("2.5")
    calc.stop_price = Decimal("136.05")
    calc.take_profit = Decimal("122.39")
    calc.fee_cost_usd = Decimal("0.27")
    calc.slippage_cost_usd = Decimal("0.25")
    calc.effective_risk_usd = Decimal("5.0")
    return calc


def _alert_engine():
    ae = MagicMock()
    ae.send_signal_triggered = AsyncMock()
    ae.send_position_opened = AsyncMock()
    ae.send_position_closed = AsyncMock()
    ae.send_daily_halted = AsyncMock()
    return ae


def _trade_writer(trade_id: str = "trade-001"):
    tw = MagicMock()
    trade = MagicMock()
    trade.id = trade_id
    tw.open_trade = AsyncMock(return_value=trade)
    tw.close_trade = AsyncMock()
    return tw


def _session_factory():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return factory


# ---------------------------------------------------------------------------
# Import ScanLoop with all required deps mocked
# ---------------------------------------------------------------------------

def _make_scan_loop(alert_engine=None, trade_writer=None):
    from scanner.scan_loop import ScanLoop

    config = MagicMock()
    config.taker_fee_rate = 0.0006
    config.slippage_rate = 0.0005

    sl = ScanLoop(
        config=config,
        candle_store=MagicMock(),
        universe_manager=MagicMock(),
        ws_client=MagicMock(),
        rest_client=MagicMock(),
        regime_detector=MagicMock(),
        signal_manager=MagicMock(),
        risk_engine=MagicMock(),
        session_factory=_session_factory(),
        alert_engine=alert_engine,
        trade_writer=trade_writer,
    )
    sl._regime = Regime.BEARISH
    return sl


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_signal_triggered_called_when_risk_approved() -> None:
    """AlertEngine.send_signal_triggered fires when risk is approved."""
    ae = _alert_engine()
    sl = _make_scan_loop(alert_engine=ae)
    sig = _signal(SignalState.TRIGGERED)
    calc = _calculation()

    # Seed triggered signal + approved risk calculation
    sl._signal_manager.active_signals = [sig]
    sl._risk_calculations[sig.signal_id] = calc

    # Simulate _handle_triggered approval path
    sym_info = MagicMock()
    sl._symbol_info_cache[sig.symbol] = sym_info
    decision = MagicMock()
    decision.approved = True
    decision.calculation = calc
    sl._risk_engine.approve = MagicMock(return_value=decision)

    candle = _candle()
    candle.open_time = sig.triggered_at  # same candle as trigger
    await sl._handle_triggered(candle)

    # Let fire-and-forget tasks run
    await asyncio.sleep(0)
    ae.send_signal_triggered.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_position_opened_and_trade_db_written() -> None:
    """AlertEngine.send_position_opened and TradeWriter.open_trade called on ACTIVE."""
    ae = _alert_engine()
    tw = _trade_writer()
    sl = _make_scan_loop(alert_engine=ae, trade_writer=tw)
    sig = _signal(SignalState.TRIGGERED)
    calc = _calculation()
    sl._risk_calculations[sig.signal_id] = calc
    sl._signal_manager.active_signals = [sig]
    sl._signal_manager.mark_active = AsyncMock()

    candle = _candle()
    # triggered_at < candle.open_time to trigger promotion
    sig.triggered_at = candle.open_time - timedelta(hours=1)

    await sl._promote_triggered_signals(candle)
    await asyncio.sleep(0)

    ae.send_position_opened.assert_awaited_once()
    tw.open_trade.assert_awaited_once()
    assert sig.signal_id in sl._open_trade_ids


@pytest.mark.asyncio
async def test_send_position_closed_and_trade_db_closed_on_tp_hit() -> None:
    """AlertEngine.send_position_closed and TradeWriter.close_trade called on TP_HIT."""
    ae = _alert_engine()
    tw = _trade_writer()
    sl = _make_scan_loop(alert_engine=ae, trade_writer=tw)

    sig = _signal(SignalState.ACTIVE)
    calc = _calculation()
    sl._risk_calculations[sig.signal_id] = calc
    sl._open_trade_ids[sig.signal_id] = "trade-001"
    sl._signal_manager.active_signals = [sig]
    sl._signal_manager.mark_terminal = AsyncMock()
    sl._risk_engine.check_daily_limits = MagicMock(return_value=MagicMock(approved=True))

    # Candle low hits TP (SHORT: low <= take_profit)
    candle = _candle()
    candle.low = Decimal("122.0")   # <= 122.39

    await sl._check_active_signals(candle)
    await asyncio.sleep(0)

    ae.send_position_closed.assert_awaited_once()
    tw.close_trade.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_daily_halted_called_on_limit_breach() -> None:
    """AlertEngine.send_daily_halted fires when daily risk limit is breached."""
    ae = _alert_engine()
    sl = _make_scan_loop(alert_engine=ae)

    halt_decision = MagicMock()
    halt_decision.approved = False
    halt_decision.reason = "max daily loss reached"
    sl._risk_engine.check_daily_limits = MagicMock(return_value=halt_decision)
    sl._daily_session.halt = MagicMock()

    sl._halt_session_if_needed()
    await asyncio.sleep(0)

    ae.send_daily_halted.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_error_when_alert_engine_is_none() -> None:
    """ScanLoop operates silently when AlertEngine is not configured."""
    sl = _make_scan_loop(alert_engine=None, trade_writer=None)
    sl._risk_engine.check_daily_limits = MagicMock(return_value=MagicMock(approved=True))

    # No exception when alert_engine is None
    candle = _candle()
    sl._signal_manager.active_signals = []
    await sl._check_active_signals(candle)
    await sl._promote_triggered_signals(candle)
