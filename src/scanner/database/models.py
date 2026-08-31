"""SQLAlchemy models for scanner persistence.

Prices and monetary amounts use NUMERIC columns so values retain Decimal precision.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all persistence models."""


class Signal(Base):
    """Persisted state for a detected trading setup."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    tp_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class StateTransition(Base):
    """An immutable record of a signal lifecycle transition."""

    __tablename__ = "state_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("signals.id"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(16), nullable=False)
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class Trade(Base):
    """A completed or open paper/live trade record."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    signal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("signals.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    fee_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    slippage_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DailySession(Base):
    """UTC-day risk and trading totals."""

    __tablename__ = "daily_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    trades_taken: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(38, 18), default=Decimal("0"), nullable=False
    )
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class AuditLog(Base):
    """Structured audit event retained independently of application logs."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
