# TASK_014_RED_TEAM.md
# Reviewer: GEMINI (Adversarial)
# Task ID: T014
# Date: 2026-09-01

---

## Summary

Adversarial review of T014 BacktestEngine. Focus: empty edge cases, metric
zero-safety, session factory, max_drawdown correctness, Sharpe edge cases,
and the CTO-applied BTC close_time look-ahead fix.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| A-01 | candles_1h empty list | ✅ PASS | Lines 219-221: returns empty_result immediately |
| A-02 | candles_1h has 1 element | ✅ PASS | Loop runs once; warmup=50 skips it; zero trades; valid empty result |
| A-03 | btc_candles_4h empty | ✅ PASS | btc_buffer stays empty; classify() returns UNDEFINED; no signals — correct |
| A-04 | All trades CANCELLED (no TP/SL records) | ✅ PASS | trade_records=[]; _compute_metrics returns all-zero dict |
| A-05 | equity only goes up (max_drawdown=0) | ✅ PASS | Line 603: max(0, peak-equity); if equity always grows, peak==equity, drawdown==0 |
| A-06 | std_daily_pnl=0 (all same PnL per day) | ✅ PASS | Line 620: if variance==_ZERO: return _ZERO |
| A-07 | warmup > len(candles_1h) | ✅ PASS | Every candle skipped via index < min_warmup_candles; zero trades; valid empty result |
| A-08 | Null session factory type compatibility | ✅ PASS | @asynccontextmanager yields _NullAsyncSession; cast() satisfies type checker |
| A-09 | _NullAsyncSession.add() is synchronous | ✅ PASS | Line 145: plain def, not async def — matches SQLAlchemy session.add() |
| A-10 | profit_factor when all trades are wins | ✅ PASS | Line 584-588: losses=[] → returns _ZERO (no losses denominator guard) |
| A-11 | max_drawdown starts at peak=ZERO | ✅ PASS | Correct for accounts starting at ZERO equity; first loss will be drawdown |
| A-12 | run() never raises to caller | ✅ PASS | Lines 200-207: outer except catches all; returns _empty_result |
| A-13 | 352 tests passing after CTO BTC fix | ✅ PASS | Zero regression |
| A-14 | BTC close_time fix correct | ✅ PASS | See Critical Issue below (now RESOLVED) |

---

## Critical Issue — RESOLVED BY CTO: BTC Buffer Look-Ahead (Sonnet L-03)

**Original bug**: `_advance_btc_to` used `open_time > target_time`, which
included BTC 4H candles whose close_time was in the future.

**CTO fix applied**: `candle_close_time = btc_candle.open_time + _BTC_CANDLE_DURATION;
if candle_close_time > target_time: return`

**Verification**: At target=05:00, btc[1] (open=04:00, close=08:00) is excluded.
At target=09:00, btc[1] (close=08:00 ≤ 09:00) is included. Correct. ✅

Two existing tests updated to reflect the correct close_time semantics:
- `test_btc_buffer_aligned_to_1h_candle_time`: pointer [2]→[1]; buffer excludes btc[1]
- `test_forming_btc_candle_is_not_revealed_to_regime_buffer`: pointer [1]→[0]

---

## Remaining Observations (Non-Blocking)

### F-01 — avg_r uses entry-to-stop distance, not actual risk_usd

`avg_risk = abs(entry - stop) × qty` — this approximates risk per trade in USD.
This is correct for R calculation. Minor note: does not include fees/slippage
in the risk denominator. For a $5 risk engine, avg_risk ≈ $5.00 ± rounding.

### F-02 — Sharpe uses exit_candle_time for daily grouping, not entry

Daily PnL is grouped by exit date. Trades that open on day N but close on day N+1
are attributed to day N+1. This is consistent with cash realisation timing and
is the correct accounting convention. ✅

---

## Release Recommendation

**APPROVED** — BTC look-ahead bug resolved by CTO. 352/352 pass. All edge
cases handled. Failure isolation (run() never raises) confirmed.

---
