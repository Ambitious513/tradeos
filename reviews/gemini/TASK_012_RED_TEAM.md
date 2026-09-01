# TASK_012_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T012
# Date: 2026-09-01

---

## Summary

Adversarial review of T012 ScanLoop. Focus: _risk_calculations dict leak,
multiple active signals, signal_manager exception isolation, CandleStore
patch callback ordering, and universe refresh failure modes.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | CandleStore patch: _insert_closed before callback | ✅ PASS | Lines 101-103: candle in buffer before _process_candle fires |
| R-02 | BTCUSDT 4H candle returned early after regime refresh | ✅ PASS | Lines 117-118: `timeframe != "60" → return` stops strategy processing for BTC 4H candles |
| R-03 | signal_manager.on_candle exception isolated | ✅ PASS | Lines 126-133: exception caught; log ERROR; return |
| R-04 | risk_engine.approve exception isolated | ✅ PASS | Lines 191-198: exception caught; cancel signal |
| R-05 | Multiple ACTIVE signals detected | ✅ PASS | Lines 221-224: ERROR log; continues processing (conservative: close both) |
| R-06 | Missing risk calculation for ACTIVE signal | ✅ PASS | Lines 226-238: ERROR + CANCELLED |
| R-07 | candle.open == 0 blocks entry confirmation | ✅ PASS | Lines 143-149 |
| R-08 | Halt check after EVERY terminal outcome | ✅ PASS | Line 273: _halt_session_if_needed inside per-signal loop |
| R-09 | CANCELLED/EXPIRED do not increment trades_taken | ✅ PASS | Only SL_HIT/TP_HIT path increments (line 250) |
| R-10 | Universe refresh failure: empty instrument list | ✅ PASS | Lines 336-343: falls back to empty list; warning logged |
| R-11 | shutdown() sets both stop flag and event | ✅ PASS | Lines 107-108 |
| R-12 | stream_task.done() checked in run() loop | ✅ PASS | Lines 91-93: stream errors propagated |
| R-13 | DailySession uses candle date, not wall clock | ✅ PASS | Line 114: candle.open_time.date() |
| R-14 | 285 total tests / 29 new | ✅ PASS | Zero regression |

---

## Findings Requiring Attention (Non-Blocking)

### F-01 — `_risk_calculations` dict leak on CANCELLED / EXPIRED signals

`_risk_calculations` is populated when a signal is TRIGGERED and risk-approved
(line 208). It is cleaned up only in `_check_active_signals` (line 260) when
a terminal TP/SL outcome is recorded.

If a TRIGGERED signal is subsequently CANCELLED (e.g. regime change) or EXPIRES
(1H timeout) WITHOUT going through `_check_active_signals`, the UUID remains in
`_risk_calculations` indefinitely.

**Severity**: Low. Paper trading processes O(10s) of symbols; the leak is a small
dict entry with no downstream correctness impact. T012 already handles the
"missing risk calculation" case for ACTIVE signals.

**Recommendation for T013+**: Add cleanup:
```python
# In _signals_for or after mark_terminal/cancel:
self._risk_calculations.pop(signal.signal_id, None)
```
Or, prune stale entries on DailySession reset (simplest fix).

### F-02 — BTCUSDT 1H candles also trigger `_is_4h_btc_close`?

No — `_is_4h_btc_close` checks `candle.timeframe` implicitly via `open_time.hour % 4 == 0`.
A 1H BTCUSDT candle at hour=8 would match. However, BTCUSDT is only initialized with
`["240"]` (4H) at startup (line 347), so BTCUSDT 1H candles never enter the CandleStore.
✅ No actual false-positive risk; but the check could defensively also validate
`candle.timeframe == "240"` for clarity.

---

## Critical Issues

**None blocking release.**

---

## Recommendations

1. Add `self._risk_calculations.pop(signal.signal_id, None)` in `signal_manager.cancel()` 
   callback or in `_process_candle` cleanup pass — low priority.
2. Optionally add `and candle.timeframe == "240"` to `_is_4h_btc_close` for defensive clarity.

---

## Release Recommendation

**APPROVED** — No blocking issues. F-01 is a minor paper-trading non-issue.

---
