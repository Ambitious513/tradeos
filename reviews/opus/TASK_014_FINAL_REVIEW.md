# TASK_014_FINAL_REVIEW.md
# Reviewer: Lead CTO (Opus/Fable)
# Task ID: T014
# Date: 2026-09-01

---

## Summary

CTO final review of T014 BacktestEngine. Verifying look-ahead compliance after
Sonnet-identified fix, metric correctness, authorized interface usage, and
scope discipline.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| C-01 | 352 tests pass; 41 new T014 tests | ✅ PASS | Zero regression |
| C-02 | Sonnet L-03 FAIL resolved | ✅ PASS | close_time-based condition applied and verified |
| C-03 | _BacktestBuffer irreversible advance | ✅ PASS | ValueError on out-of-order open_time |
| C-04 | candle[i+1] not visible at step i | ✅ PASS | advance() before on_candle(); future candles never added |
| C-05 | BTC buffer: close_time > target_time guard | ✅ PASS | _BTC_CANDLE_DURATION = timedelta(hours=4) applied |
| C-06 | Entry = next candle open | ✅ PASS | _promote_triggered: candle.open after triggered_at < open_time |
| C-07 | SL wins same-candle tie | ✅ PASS | Line 379: SL_HIT if sl_hit else TP_HIT |
| C-08 | Decision A: no strategy code in backtest_engine.py | ✅ PASS | Imports approved modules; zero strategy reimplementation |
| C-09 | Decision E: null session factory isolates DB | ✅ PASS | @asynccontextmanager + _NullAsyncSession |
| C-10 | DailySession resets at UTC midnight | ✅ PASS | _reset_session_if_needed on every candle |
| C-11 | All Decimal arithmetic; no float in metrics | ✅ PASS | Decimal(365).sqrt(); sum(start=_ZERO); Decimal(len()) |
| C-12 | Sharpe 365-day annualized; 0 if < 2 days | ✅ PASS | Lines 614-622 |
| C-13 | run() never raises; returns empty_result | ✅ PASS | Outer except wraps _run_replay |
| C-14 | BacktestResult and TradeRecord are frozen | ✅ PASS | @dataclass(frozen=True) |
| C-15 | Authorized patches only (protocols.py, 2×2-line type annotation change) | ✅ PASS | Confirmed |
| C-16 | scan_loop.py, strategy/, risk/ not modified | ✅ PASS | Scope discipline maintained |
| C-17 | mypy strict + ruff + black clean | ✅ PASS | As reported by Codex |

---

## BTC Look-Ahead Fix — CTO Note

The Sonnet audit correctly identified that `open_time > target_time` allowed
the BTC 4H candle (open_time=T, close_time=T+4H) to enter the buffer at
target_time=T, making close price T+4H visible when simulation was at T.

The correct condition `close_time > target_time` (where close_time = open_time
+ 4H) delays inclusion until target_time >= T+4H — matching when a live
CandleStore would first hold this closed 4H BTC candle.

The fix also correctly handles the `is_closed=False` test case: forming candles
(close_time in the future) are held at pointer position and re-examined on
subsequent advance calls. Old behavior permanently skipped them.

---

## GATE-2 Requirement

Before this engine can be used to validate the strategy, real historical
data must be fed through BacktestEngine.run() and the resulting
BacktestResult reviewed by the human. Specifically:

- Run over >= 3 months of 1H ETHUSDT (or universe sample) history
- Confirm non-UNDEFINED regime for > 50% of candle window (BTC history adequate)
- Review: total_trades, win_rate, profit_factor, expectancy, max_drawdown
- Human must explicitly approve results before Paper Trading (T015) begins

---

## Release Decision

**APPROVED**

All 17 CTO criteria verified. Sonnet mandatory look-ahead audit satisfied
after authorized CTO fix. 352/352 tests. GATE-2 pending human review of
real backtest results on historical data.

---
