#!/usr/bin/env python3
"""GATE-2 Historical Backtest Runner — A+ Scanner v1.0.

Runs BacktestEngine over two universe passes and prints a structured report
for human GATE-2 review.

Pass 1 — New Listings (14-60 days old):
    Strategy-relevant market. New coins exhibit the pump/dump extremes that
    SHORT_EXHAUSTION and LONG_EXHAUSTION are designed to capture.

Pass 2 — Top 20 USDT Perpetuals by 24H Turnover (control group):
    Established liquid coins. Validates strategy performance outside of
    the new-listing context.

Usage:
    python scripts/run_backtest.py

Requirements:
    .env must contain BYBIT_API_KEY and BYBIT_API_SECRET (read-only keys).
    BYBIT_TESTNET must be false (or absent).

Candle windows:
    1H symbol candles : 90 days  = 2160 candles  (3 pages of 1000)
    4H BTC candles    : 123 days = 738  candles  (1 page)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import aiohttp

sys.path.insert(0, "src")

from scanner.backtest import BacktestEngine, BacktestResult
from scanner.config import ScannerConfig
from scanner.market_data.bybit_rest import BybitRESTClient
from scanner.market_data.models import SymbolInfo
from scanner.models import Candle

_BYBIT_MAINNET_BASE   = "https://api.bybit.com"
_INSTRUMENTS_URL      = f"{_BYBIT_MAINNET_BASE}/v5/market/instruments-info"
_1H_DAYS              = 180
_BTC_4H_DAYS          = 213
_1H_CANDLES_NEEDED    = _1H_DAYS * 24        # 4320 — used for Pass 2 (top volume)
_1H_CANDLES_NEW       = 60 * 24              # 1440 — Pass 1 new listings (max 60d data)
_BTC_CANDLES_NEEDED   = _BTC_4H_DAYS * 6    # 1278
_BATCH_SIZE           = 1000
_NEW_LISTING_MIN_DAYS = 14
_NEW_LISTING_MAX_DAYS = 60
_NEW_LISTING_MIN_VOL  = 5_000_000            # 5M USD 24H turnover — filters dead coins
_TOP_VOLUME_COUNT     = 20
_VOLUME_EXCLUDE       = {"BTCUSDT", "ETHUSDT"}
_WARMUP_CANDLES       = 50


async def _fetch_new_listing_symbols(
    rest: BybitRESTClient,
    now: datetime,
) -> list[tuple[str, SymbolInfo]]:
    """Return (symbol, SymbolInfo) pairs for coins listed 14–60 days ago.

    Volume filter uses the tickers endpoint (turnover_24h) — the correct source.
    The instruments-info endpoint does NOT carry volume data.
    """
    min_ts = int((now - timedelta(days=_NEW_LISTING_MAX_DAYS)).timestamp() * 1000)
    max_ts = int((now - timedelta(days=_NEW_LISTING_MIN_DAYS)).timestamp() * 1000)

    # Fetch tickers first for volume cross-reference.
    tickers = await rest.get_tickers_24h()
    volume_map = {t.symbol: float(t.turnover_24h) for t in tickers}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            _INSTRUMENTS_URL,
            params={"category": "linear", "limit": 1000},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            data = await response.json()
    rows = data.get("result", {}).get("list", [])
    candidates: list[str] = []
    for row in rows:
        if row.get("quoteCoin") != "USDT":
            continue
        if row.get("status") != "Trading":
            continue
        launch_ms = int(row.get("launchTime", 0))
        if not (min_ts <= launch_ms <= max_ts):
            continue
        sym = row["symbol"]
        # Volume filter: skip dead coins using tickers data (correct source).
        if volume_map.get(sym, 0.0) < _NEW_LISTING_MIN_VOL:
            continue
        candidates.append(sym)
    all_info = await rest.get_instruments_info()
    info_map = {s.symbol: s for s in all_info}
    pairs = [(sym, info_map[sym]) for sym in candidates if sym in info_map]
    pairs.sort(key=lambda p: p[0])
    print(f"  (volume-filtered to {len(pairs)} with >${_NEW_LISTING_MIN_VOL/1_000_000:.0f}M 24H turnover)")
    return pairs


async def _fetch_top_volume_symbols(
    rest: BybitRESTClient,
) -> list[tuple[str, SymbolInfo]]:
    tickers = await rest.get_tickers_24h()
    sorted_tickers = sorted(
        (t for t in tickers if t.symbol not in _VOLUME_EXCLUDE),
        key=lambda t: t.turnover_24h,
        reverse=True,
    )
    top = [t.symbol for t in sorted_tickers[:_TOP_VOLUME_COUNT]]
    all_info = await rest.get_instruments_info()
    info_map = {s.symbol: s for s in all_info}
    return [(sym, info_map[sym]) for sym in top if sym in info_map]


async def _fetch_candles_paginated(
    rest: BybitRESTClient,
    symbol: str,
    interval: str,
    needed: int,
    end_time_ms: int,
) -> list[Candle]:
    all_candles: list[Candle] = []
    current_end = end_time_ms
    while len(all_candles) < needed:
        batch_size = min(_BATCH_SIZE, needed - len(all_candles))
        batch = await rest.get_klines(
            symbol, interval, limit=batch_size, end_time_ms=current_end
        )
        if not batch:
            break
        oldest_ms = int(batch[0].open_time.timestamp() * 1000) - 1
        all_candles = batch + all_candles
        if oldest_ms >= current_end:
            break
        current_end = oldest_ms
    return all_candles[-needed:]


def _fmt_pnl(value: Decimal) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}${value:.4f}"


def _fmt_pct(value: Decimal) -> str:
    return f"{value * 100:.1f}%"


def _print_pass_header(pass_name: str, count: int) -> None:
    print()
    print("=" * 70)
    print(f"  {pass_name}  ({count} symbols)")
    print("=" * 70)


def _print_symbol_result(result: BacktestResult) -> None:
    if result.total_trades == 0:
        print(f"  {result.symbol:<16} -- no trades in window")
        return
    print(
        f"  {result.symbol:<16} "
        f"trades={result.total_trades:>3}  "
        f"win={_fmt_pct(result.win_rate):<7}  "
        f"pnl={_fmt_pnl(result.total_net_pnl):<12}  "
        f"pf={result.profit_factor:.2f}  "
        f"dd={_fmt_pnl(result.max_drawdown):<10}  "
        f"sharpe={result.sharpe_ratio:.2f}"
    )


def _print_aggregate(results: list[BacktestResult], label: str) -> None:
    traded = [r for r in results if r.total_trades > 0]
    if not traded:
        print(f"\n  {label}: no trades recorded.")
        return
    total_trades = sum(r.total_trades for r in traded)
    total_wins   = sum(r.winning_trades for r in traded)
    total_pnl    = sum(r.total_net_pnl for r in traded)
    avg_sharpe   = sum(r.sharpe_ratio for r in traded) / len(traded)
    max_dd       = max(r.max_drawdown for r in traded)
    win_rate     = Decimal(total_wins) / Decimal(total_trades)
    print()
    print(f"  -- {label} AGGREGATE --")
    print(f"  Symbols with trades : {len(traded)} / {len(results)}")
    print(f"  Total trades        : {total_trades}")
    print(f"  Overall win rate    : {_fmt_pct(win_rate)}")
    print(f"  Combined net PnL    : {_fmt_pnl(total_pnl)}")
    print(f"  Avg Sharpe ratio    : {avg_sharpe:.3f}")
    print(f"  Max single DD       : {_fmt_pnl(max_dd)}")


def _gate2_verdict(pass1: list[BacktestResult], pass2: list[BacktestResult]) -> None:
    all_results = pass1 + pass2
    traded = [r for r in all_results if r.total_trades > 0]
    if not traded:
        verdict = "BLOCKED -- no trades recorded. Check BTC history and universe."
        gate = "BLOCKED"
    else:
        total_trades = sum(r.total_trades for r in traded)
        total_wins   = sum(r.winning_trades for r in traded)
        total_pnl    = sum(r.total_net_pnl for r in traded)
        win_rate     = Decimal(total_wins) / Decimal(total_trades)
        print()
        print("=" * 70)
        print("  GATE-2 SUMMARY")
        print("=" * 70)
        print(f"  Combined trades  : {total_trades}")
        print(f"  Combined win     : {_fmt_pct(win_rate)}")
        print(f"  Combined PnL     : {_fmt_pnl(total_pnl)}")
        print()
        if total_trades < 10:
            gate    = "WARNING"
            verdict = "INSUFFICIENT DATA -- fewer than 10 trades. Extend window or universe."
        elif win_rate >= Decimal("0.50") and total_pnl > Decimal(0):
            gate    = "PASS CANDIDATE"
            verdict = "Review results above, then approve to proceed to T015 (Paper Trading)."
        elif win_rate >= Decimal("0.45") and total_pnl > Decimal(0):
            gate    = "BORDERLINE"
            verdict = "Positive PnL but low win rate. Review per-symbol breakdown."
        else:
            gate    = "FAIL"
            verdict = "Strategy needs review before paper trading begins."
    print(f"  GATE-2 [{gate}]")
    print(f"  {verdict}")
    print()
    print("  Human decision required. No T015 dispatch until gate is approved.")
    print("=" * 70)


def _print_btc_regime_distribution(
    btc_candles_4h: list[Candle], config: ScannerConfig
) -> None:
    """Classify every 4H BTC candle and print a regime frequency table.

    This runs the approved RegimeDetector sequentially over the BTC buffer so
    the caller sees exactly what fraction of the window was BULLISH, BEARISH,
    NEUTRAL, or UNDEFINED before any symbol data is fetched.
    """
    # Import here to avoid circular issues when sys.path is not yet set.
    from scanner.backtest.backtest_engine import _BacktestBuffer, _BacktestCandleStore
    from scanner.regime.detector import RegimeDetector

    buf   = _BacktestBuffer(max_size=250)
    store = _BacktestCandleStore(buf)
    det   = RegimeDetector(store, config)

    counts: dict[str, int] = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0, "UNDEFINED": 0}
    for candle in btc_candles_4h:
        if candle.is_closed:
            buf.advance(candle)
        regime = det.classify()
        key = regime.value if regime.value in counts else "UNDEFINED"
        counts[key] += 1

    total = max(sum(counts.values()), 1)
    tradeable = counts["BULLISH"] + counts["BEARISH"]
    pct_tradeable = tradeable / total * 100

    print()
    print("  -- BTC REGIME DISTRIBUTION (4H candles) --")
    for label, count in counts.items():
        bar = "#" * int(count / total * 30)
        print(f"  {label:<10} {count:>4} candles  ({count/total*100:5.1f}%)  {bar}")
    print(f"  Tradeable (BULLISH+BEARISH): {pct_tradeable:.1f}% of window")
    if pct_tradeable < 15:
        print(
            "  WARNING: <15% of window is tradeable. "
            "Consider testing over a different date range."
        )
    elif pct_tradeable < 30:
        print("  NOTE: Low tradeable window. Signal count will be limited.")
    else:
        print("  Window contains adequate BULLISH/BEARISH time.")
    print()


async def _run_pass(
    rest: BybitRESTClient,
    config: ScannerConfig,
    universe: list[tuple[str, SymbolInfo]],
    btc_candles_4h: list[Candle],
    now_ms: int,
    is_pass1: bool = False,
) -> list[BacktestResult]:
    candles_needed = _1H_CANDLES_NEW if is_pass1 else _1H_CANDLES_NEEDED
    results: list[BacktestResult] = []
    for symbol, symbol_info in universe:
        print(f"    {symbol:<16} ...", end=" ", flush=True)
        try:
            candles_1h = await _fetch_candles_paginated(
                rest, symbol, "60", candles_needed, now_ms
            )
            if len(candles_1h) < _WARMUP_CANDLES + 2:
                print(f"skipped ({len(candles_1h)} candles -- not enough history)")
                continue
            engine = BacktestEngine(config, symbol_info)
            result = await engine.run(
                symbol, candles_1h, btc_candles_4h, _WARMUP_CANDLES
            )
            results.append(result)
            print(
                f"{len(candles_1h)} candles  "
                f"{result.total_trades} trades  "
                f"win={_fmt_pct(result.win_rate)}"
            )
        except Exception as exc:
            print(f"ERROR -- {type(exc).__name__}: {exc}")
    return results


async def main(end_dt: datetime | None = None) -> None:
    if end_dt is None:
        end_dt = datetime.now(UTC)

    print()
    print("=" * 70)
    print("  A+ SCANNER -- GATE-2 BACKTEST RUNNER v1.0")
    print(f"  window end: {end_dt.strftime('%Y-%m-%d')} UTC  |  "
          f"{_1H_DAYS}-day window  |  2 passes")
    print("=" * 70)

    config = ScannerConfig()

    if not config.bybit_api_key:
        print("\n  BYBIT_API_KEY missing from .env -- cannot proceed.")
        return

    if config.bybit_testnet:
        print(
            "\n  WARNING: BYBIT_TESTNET=true. "
            "Add BYBIT_TESTNET=false to .env for mainnet data."
        )

    rest   = BybitRESTClient(config)
    now    = end_dt
    now_ms = int(now.timestamp() * 1000)

    print(f"\n  Fetching BTC 4H candles ({_BTC_4H_DAYS} days) ...", end=" ", flush=True)
    btc_candles_4h = await _fetch_candles_paginated(
        rest, "BTCUSDT", "240", _BTC_CANDLES_NEEDED, now_ms
    )
    print(f"done ({len(btc_candles_4h)} candles)")
    if len(btc_candles_4h) < 200:
        print(
            "  WARNING: Fewer than 200 BTC 4H candles available. "
            "Regime will be UNDEFINED throughout."
        )

    # ── BTC Regime Distribution ────────────────────────────────────────────
    # Show how much of the window was tradeable BEFORE spending time on symbols.
    _print_btc_regime_distribution(btc_candles_4h, config)


    # Pass 1 -- New Listings
    print(
        f"\n  Scanning for new listings "
        f"({_NEW_LISTING_MIN_DAYS}-{_NEW_LISTING_MAX_DAYS} days old) ...",
        end=" ", flush=True,
    )
    new_listing_universe = await _fetch_new_listing_symbols(rest, now)
    print(f"found {len(new_listing_universe)} symbols")

    if new_listing_universe:
        _print_pass_header(
            "PASS 1 -- NEW LISTINGS (strategy-relevant universe)",
            len(new_listing_universe),
        )
        pass1_results = await _run_pass(
            rest, config, new_listing_universe, btc_candles_4h, now_ms,
            is_pass1=True,
        )
        print()
        for r in pass1_results:
            _print_symbol_result(r)
        _print_aggregate(pass1_results, "PASS 1")
    else:
        print("  No new listings found -- Pass 1 skipped.")
        pass1_results = []

    # Pass 2 -- Top Volume Control
    print(
        f"\n  Fetching top {_TOP_VOLUME_COUNT} symbols by 24H turnover ...",
        end=" ", flush=True,
    )
    top_volume_universe = await _fetch_top_volume_symbols(rest)
    print(f"done ({len(top_volume_universe)} symbols)")

    _print_pass_header(
        "PASS 2 -- TOP VOLUME CONTROL GROUP",
        len(top_volume_universe),
    )
    pass2_results = await _run_pass(
        rest, config, top_volume_universe, btc_candles_4h, now_ms
    )
    print()
    for r in pass2_results:
        _print_symbol_result(r)
    _print_aggregate(pass2_results, "PASS 2")

    _gate2_verdict(pass1_results, pass2_results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GATE-2 backtest runner — A+ Scanner v1.0",
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "End date for the backtest window (UTC, inclusive). "
            "Defaults to today. "
            "Example: --end-date 2024-12-31 to test the Nov-Dec 2024 BTC bull run."
        ),
    )
    args = parser.parse_args()

    if args.end_date:
        try:
            _end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            print(f"ERROR: --end-date must be YYYY-MM-DD, got: {args.end_date!r}")
            sys.exit(1)
    else:
        _end_dt = datetime.now(UTC)

    asyncio.run(main(_end_dt))
