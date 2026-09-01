"""A+ Scanner — daily performance report CLI.

Usage:
    python scripts/report.py
    python scripts/report.py --date 2026-09-01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import func, select

from scanner.database.connection import get_session
from scanner.database.models import DailySession, Signal, StateTransition, Trade


async def _report(target_date: date) -> None:
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    
    async with get_session() as session:
        # Signals detected today
        sig_result = await session.execute(
            select(func.count()).select_from(Signal).where(
                Signal.detected_at >= start, Signal.detected_at < end
            )
        )
        total_signals: int = sig_result.scalar_one()

        # Triggered count (signals that reached TRIGGERED or beyond)
        triggered_result = await session.execute(
            select(func.count()).select_from(StateTransition).where(
                StateTransition.to_state == "TRIGGERED",
                StateTransition.timestamp >= start,
                StateTransition.timestamp < end,
            )
        )
        triggered_count: int = triggered_result.scalar_one()

        # Trades closed today
        trades_result = await session.execute(
            select(Trade).where(
                Trade.closed_at >= start, Trade.closed_at < end
            )
        )
        closed_trades = trades_result.scalars().all()

        tp_hits = [t for t in closed_trades if t.pnl_usd is not None and t.pnl_usd >= Decimal("0")]
        sl_hits = [t for t in closed_trades if t.pnl_usd is not None and t.pnl_usd < Decimal("0")]
        net_pnl = sum((t.pnl_usd for t in closed_trades if t.pnl_usd), Decimal("0"))

        # Open positions
        open_result = await session.execute(
            select(func.count()).select_from(Trade).where(Trade.closed_at.is_(None))
        )
        open_positions: int = open_result.scalar_one()

        # Daily session halt status
        ds_result = await session.execute(
            select(DailySession).where(DailySession.date == target_date)
        )
        daily_session = ds_result.scalar_one_or_none()
        halted = daily_session.is_halted if daily_session else False

    expired_cancelled = total_signals - triggered_count
    tp_pnl = sum((t.pnl_usd for t in tp_hits if t.pnl_usd), Decimal("0"))
    sl_pnl = sum((t.pnl_usd for t in sl_hits if t.pnl_usd), Decimal("0"))

    w = 46
    sep = "\u2550" * w

    def fmt_pnl(v: Decimal) -> str:
        return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"

    print()
    print(f"A+ Scanner \u2014 Daily Report  {target_date}  UTC")
    print(sep)
    print(f"Signals detected today    : {total_signals:>4}")
    print(f"  TRIGGERED               : {triggered_count:>4}")
    print(f"  EXPIRED / CANCELLED     : {max(expired_cancelled, 0):>4}")
    print(f"Trades today              : {len(closed_trades):>4}")
    print(f"  TP HIT                  : {len(tp_hits):>4}  ({fmt_pnl(tp_pnl)})")
    print(f"  SL HIT                  : {len(sl_hits):>4}  ({fmt_pnl(sl_pnl)})")
    print(f"Net PnL today             : {fmt_pnl(net_pnl):>14}")
    print(f"Daily session halted      : {'Yes' if halted else 'No':>4}")
    print(sep)
    print(f"Open positions            : {open_positions:>4}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="A+ Scanner daily report")
    parser.add_argument(
        "--date",
        type=lambda s: date.fromisoformat(s),
        default=datetime.now(UTC).date(),
        help="Report date (YYYY-MM-DD). Defaults to today UTC.",
    )
    args = parser.parse_args()
    asyncio.run(_report(args.date))


if __name__ == "__main__":
    main()
