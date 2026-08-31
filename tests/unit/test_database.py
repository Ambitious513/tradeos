"""Tests for the asynchronous database schema and persistence models."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from scanner.database.migrations import create_all_tables
from scanner.database.models import AuditLog, DailySession, Signal, StateTransition, Trade


async def test_create_all_tables_succeeds(db_engine: AsyncEngine) -> None:
    """Schema creation completes on a fresh in-memory SQLite engine."""
    await create_all_tables(db_engine)


async def test_create_all_tables_idempotent(db_engine: AsyncEngine) -> None:
    """Schema creation can be repeated safely."""
    await create_all_tables(db_engine)
    await create_all_tables(db_engine)


async def test_signal_insert_and_query(db_session: AsyncSession) -> None:
    """Signals can be persisted and loaded by their unique ID."""
    now = datetime.now(UTC)
    signal = Signal(
        symbol="ETHUSDT",
        direction="SHORT",
        state="DETECTED",
        detected_at=now,
        entry_price=Decimal("100"),
        stop_price=Decimal("105"),
        tp_price=Decimal("90"),
        score=80,
        expiration_time=now + timedelta(hours=4),
    )
    db_session.add(signal)
    await db_session.commit()
    loaded = await db_session.scalar(select(Signal).where(Signal.id == signal.id))
    assert loaded is not None
    assert loaded.entry_price == Decimal("100")


async def test_state_transition_insert(db_session: AsyncSession) -> None:
    """Transitions retain their parent signal association."""
    now = datetime.now(UTC)
    signal = Signal(
        symbol="ETHUSDT",
        direction="SHORT",
        state="WATCHING",
        detected_at=now,
        expiration_time=now + timedelta(hours=4),
    )
    db_session.add(signal)
    await db_session.flush()
    db_session.add(
        StateTransition(
            signal_id=signal.id,
            from_state="DETECTED",
            to_state="WATCHING",
            reason="initial_conditions_confirmed",
        )
    )
    await db_session.commit()
    transition = await db_session.scalar(select(StateTransition))
    assert transition is not None
    assert transition.signal_id == signal.id


async def test_trade_insert_and_query(db_session: AsyncSession) -> None:
    """Trade records use Decimal-compatible values for monetary fields."""
    now = datetime.now(UTC)
    signal = Signal(
        symbol="ETHUSDT",
        direction="SHORT",
        state="ACTIVE",
        detected_at=now,
        expiration_time=now + timedelta(hours=4),
    )
    db_session.add(signal)
    await db_session.flush()
    db_session.add(
        Trade(
            signal_id=signal.id,
            direction="SHORT",
            qty=Decimal("1.5"),
            entry_price=Decimal("100"),
            exit_price=Decimal("90"),
            pnl_usd=Decimal("15"),
            fee_usd=Decimal("0.11"),
            slippage_usd=Decimal("0.10"),
            opened_at=now,
            closed_at=now + timedelta(hours=1),
        )
    )
    await db_session.commit()
    trade = await db_session.scalar(select(Trade))
    assert trade is not None
    assert trade.pnl_usd == Decimal("15")


async def test_daily_session_insert_and_query(db_session: AsyncSession) -> None:
    """A single UTC day can retain its risk totals."""
    session = DailySession(
        date=date(2026, 8, 31),
        trades_taken=2,
        realized_pnl=Decimal("4.5"),
        is_halted=False,
    )
    db_session.add(session)
    await db_session.commit()
    loaded = await db_session.scalar(select(DailySession))
    assert loaded is not None
    assert loaded.trades_taken == 2


async def test_audit_log_insert(db_session: AsyncSession) -> None:
    """Audit events can be retained with their structured payload."""
    db_session.add(
        AuditLog(
            component="test",
            event="test_event",
            level="INFO",
            data_json='{"status": "ok"}',
        )
    )
    await db_session.commit()
    audit_log = await db_session.scalar(select(AuditLog))
    assert audit_log is not None
    assert audit_log.event == "test_event"
