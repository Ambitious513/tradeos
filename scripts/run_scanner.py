"""A+ Scanner -- Live Scanner Entry Point (GATE-3 Observation Mode).

Usage:
    python scripts/run_scanner.py

Reads all config from .env.  Observation mode is the default -- no orders
are placed.  Telegram alerts fire for every TRIGGERED signal.

GATE-3 checklist:
  [x] GATE-2 approved (backtest engine validated)
  [ ] 7-day observation run -- human approves before paper execution
  [ ] GATE-3 approval required before any order is placed
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scanner.alerting.alert_engine import AlertEngine
from scanner.candle_store.candle_store import CandleStore
from scanner.candle_store.universe_manager import UniverseManager
from scanner.config import ScannerConfig
from scanner.database.connection import create_engine, get_session
from scanner.database.models import Base
from scanner.database.trade_writer import TradeWriter
from scanner.logging_setup import get_logger
from scanner.market_data.bybit_rest import BybitRESTClient
from scanner.market_data.bybit_ws import BybitWebSocketClient
from scanner.regime.detector import RegimeDetector
from scanner.risk.risk_engine import RiskEngine
from scanner.scan_loop import ScanLoop
from scanner.strategy.signal_manager import SignalManager

logger = get_logger("runner")


async def _run() -> None:
    # ── Config ────────────────────────────────────────────────────────────────
    config = ScannerConfig()

    print()
    print("=" * 60)
    print("  A+ SCANNER -- LIVE RUNNER  (GATE-3 Observation Mode)")
    print("=" * 60)
    print(f"  Environment : {config.environment}")
    print(f"  Testnet     : {config.bybit_testnet}")
    print(f"  Telegram    : {'configured' if config.telegram_bot_token else 'NOT configured'}")
    print(f"  New listings: {config.universe_new_listing_days}-day window")
    print()

    if config.bybit_testnet:
        print("  WARNING: BYBIT_TESTNET=true -- set BYBIT_TESTNET=false in .env for mainnet")

    # ── Database ──────────────────────────────────────────────────────────────
    print("  Initialising database...", end=" ", flush=True)
    engine = create_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("done")

    # ── Transport clients ─────────────────────────────────────────────────────
    rest_client = BybitRESTClient(config)

    # Placeholder -- will be filled by ScanLoop._process_candle after ScanLoop is created
    _ws_callback_holder: list = []

    async def _ws_on_candle(candle) -> None:  # type: ignore[no-untyped-def]
        if _ws_callback_holder:
            await _ws_callback_holder[0](candle)

    ws_client = BybitWebSocketClient(config, on_candle=_ws_on_candle)

    # ── Candle store (callback wired after ScanLoop created) ──────────────────
    candle_store = CandleStore(rest_client, ws_client, config)

    # ── Strategy components ────────────────────────────────────────────────────
    session_factory = get_session
    universe_manager = UniverseManager(rest_client, config)
    regime_detector = RegimeDetector(candle_store, config)
    risk_engine = RiskEngine(config)
    signal_manager = SignalManager(candle_store, session_factory, config)

    # ── Alert + trade persistence ──────────────────────────────────────────────
    alert_engine = AlertEngine(config) if config.telegram_bot_token else None
    trade_writer = TradeWriter()

    # ── Compose ScanLoop ───────────────────────────────────────────────────────
    scan_loop = ScanLoop(
        config=config,
        candle_store=candle_store,
        universe_manager=universe_manager,
        ws_client=ws_client,
        rest_client=rest_client,
        regime_detector=regime_detector,
        signal_manager=signal_manager,
        risk_engine=risk_engine,
        session_factory=session_factory,
        alert_engine=alert_engine,
        trade_writer=trade_writer,
    )

    # Wire the WebSocket callback to ScanLoop._process_candle
    _ws_callback_holder.append(scan_loop._process_candle)

    # ── Graceful shutdown ──────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()

    def _on_signal(sig_num: int) -> None:
        logger.info("shutdown_requested", signal=sig_num)
        print(f"\n  Shutdown signal received ({sig_num}). Stopping cleanly...")
        asyncio.create_task(scan_loop.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    # ── Send startup Telegram notification ────────────────────────────────────
    if alert_engine:
        from datetime import UTC, datetime
        import aiohttp
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        startup_msg = (
            "\U0001f916 <b>A+ Scanner Started</b>\n"
            f"\U0001f550 {now}\n"
            f"Mode   : Observation (GATE-3)\n"
            f"Regime : checking...\n"
            f"Universe : {config.universe_new_listing_days}-day new listings window\n"
            "Watching for A+ SHORT setups..."
        )
        try:
            async with aiohttp.ClientSession() as sess:
                await sess.post(
                    f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                    json={"chat_id": config.telegram_chat_id, "text": startup_msg, "parse_mode": "HTML"},
                    timeout=aiohttp.ClientTimeout(total=5),
                )
        except Exception:
            pass

    print("  Scanner running. Press Ctrl+C to stop.")
    print()

    # ── Run ───────────────────────────────────────────────────────────────────
    await scan_loop.run()

    print()
    print("  Scanner stopped cleanly.")
    await rest_client.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n  Interrupted by user.")


if __name__ == "__main__":
    main()
