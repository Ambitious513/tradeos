"""Live connectivity test — sends a Telegram status message with real BTC data.

Usage: python scripts/live_test.py
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import UTC, datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BYBIT_BASE         = "https://api.bybit.com"


async def get_btc_snapshot() -> dict:
    """Fetch current BTC ticker + latest 4H candle for regime context."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 24H ticker
        r1 = await client.get(
            f"{BYBIT_BASE}/v5/market/tickers",
            params={"category": "linear", "symbol": "BTCUSDT"},
        )
        r1.raise_for_status()
        ticker = r1.json()["result"]["list"][0]

        # Last two 4H candles for simple regime assessment
        r2 = await client.get(
            f"{BYBIT_BASE}/v5/market/kline",
            params={"category": "linear", "symbol": "BTCUSDT", "interval": "240", "limit": 3},
        )
        r2.raise_for_status()
        klines = r2.json()["result"]["list"]  # newest first

    last_close  = float(klines[0][4])
    open_48h    = float(klines[2][1])
    change_48h  = (last_close - open_48h) / open_48h * 100

    price_change_24h = float(ticker.get("price24hPcnt", 0)) * 100

    if price_change_24h <= -1.5:
        regime = "BEARISH \U0001f4c9"
    elif price_change_24h >= 1.5:
        regime = "BULLISH \U0001f4c8"
    else:
        regime = "NEUTRAL \U000027a1"

    return {
        "last_price":       float(ticker["lastPrice"]),
        "high_24h":         float(ticker["highPrice24h"]),
        "low_24h":          float(ticker["lowPrice24h"]),
        "change_24h_pct":   price_change_24h,
        "change_48h_pct":   change_48h,
        "regime":           regime,
        "turnover_24h_usd": float(ticker["turnover24h"]),
    }


async def send_telegram(text: str) -> int:
    """POST a message to the configured Telegram chat. Returns HTTP status."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        })
    return r.status_code


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    print("Fetching BTC data from Bybit mainnet...")
    try:
        btc = await get_btc_snapshot()
    except Exception as e:
        print(f"Bybit fetch failed: {e}")
        sys.exit(1)

    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Check if any universe symbols would have fired
    # (observation only — no real signals checked, just BTC regime)
    regime_note = (
        "SHORT setups are <b>eligible</b> (BTC bearish regime)"
        if "BEARISH" in btc["regime"]
        else "SHORT setups are <b>not eligible</b> (regime not bearish)"
    )

    msg = (
        "\U0001f916 <b>A+ Scanner \u2014 Live Status Check</b>\n"
        f"\U0001f550 {now_utc}\n"
        "\n"
        "<b>\u25b6 BTC Regime</b>\n"
        f"  Price  :  ${btc['last_price']:,.2f}\n"
        f"  24H    :  {btc['change_24h_pct']:+.2f}%\n"
        f"  48H    :  {btc['change_48h_pct']:+.2f}%\n"
        f"  Regime :  {btc['regime']}\n"
        "\n"
        f"\U0001f4cb {regime_note}\n"
        "\n"
        "<b>System</b>\n"
        "  Status      :  \u2705 Online\n"
        "  Data source :  Bybit mainnet (read-only)\n"
        "  Mode        :  Observation (GATE-3)\n"
        "  Telegram    :  \u2705 Connected\n"
    )

    print("Sending Telegram message...")
    status = await send_telegram(msg)
    if status == 200:
        print(f"Message sent successfully (HTTP {status})")
        regime_safe = btc["regime"].encode("ascii", errors="replace").decode("ascii")
        print(f"\nBTC: ${btc['last_price']:,.2f}  24H: {btc['change_24h_pct']:+.2f}%  Regime: {regime_safe}")
    else:
        print(f"Telegram returned HTTP {status}")


if __name__ == "__main__":
    asyncio.run(main())
