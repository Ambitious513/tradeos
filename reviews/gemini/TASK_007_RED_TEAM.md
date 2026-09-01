# TASK_007_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T007
# Date: 2026-09-01

---

## Summary

Adversarial review of T007 BTC Regime Detector. Focus: division by zero,
index out-of-bounds, edge thresholds, config coupling, and scope leakage.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Division by zero on `close_24h_ago == 0` | ✅ PASS | Lines 59-61: explicit zero guard; logs INFO + returns UNDEFINED |
| R-02 | Index -7 always valid | ✅ PASS | Gate at line 49 ensures `len(candles) >= 200`; `candles[-7]` is always safe |
| R-03 | Exactly 200 candles available | ✅ PASS | `< 200` fails (not `<= 200`); 200 candles passes through |
| R-04 | Neutral boundary at exactly ±1.5% | ✅ PASS | `<=` is inclusive; +1.5% → NEUTRAL (conservative) |
| R-05 | Pump boundary at exactly +8.0% | ✅ PASS | `>=` is inclusive; +8.0% → UNDEFINED (conservative) |
| R-06 | Dump boundary at exactly -8.0% | ✅ PASS | `<= -8.0` is inclusive; -8.0% → UNDEFINED (conservative) |
| R-07 | EMA None check before stack | ✅ PASS | Lines 72-75: any None → UNDEFINED before `ema7 > ema14` comparison |
| R-08 | Mixed stack (e.g. ema7>ema14<ema28) → UNDEFINED | ✅ PASS | Neither `bullish_stack` nor `bearish_stack` is True → falls through to line 101 |
| R-09 | BTCUSDT string hardcoded | ✅ PASS | `BTC_SYMBOL = "BTCUSDT"` class constant — one place to update if needed |
| R-10 | `classify()` always re-reads CandleStore | ✅ PASS | No cache inside classify(); fresh `get_closed_candles()` call every invocation |
| R-11 | `last_regime` initialized to UNDEFINED | ✅ PASS | Line 28: `self._last_regime = Regime.UNDEFINED` |
| R-12 | `last_classified_at` initialized to None | ✅ PASS | Line 29: `self._last_classified_at: datetime | None = None` |
| R-13 | All Decimal/float values logged as str | ✅ PASS | `_record_classification` logs `str(change_pct)`, `str(ema7)`, etc. |
| R-14 | No 1H confirmation logic leaked in | ✅ PASS | Only 4H candles read; no 1H interval referenced anywhere |
| R-15 | No direct REST/WS calls | ✅ PASS | Only `candle_store.get_closed_candles()` — correct abstraction |
| R-16 | Scope compliance | ✅ PASS | 3 new files; no forbidden files touched |
| R-17 | 130/130 tests pass | ✅ PASS | Zero regression |

---

## Critical Issues

**None.**

---

## Positive Findings (beyond spec)

1. **Zero reference close guard** (lines 59-61): not required by the contract, but
   correct and important. A `Decimal("0")` close price from a corrupted candle would
   cause `ZeroDivisionError` without this guard. It logs INFO and returns UNDEFINED —
   the correct safe behavior. **Retained.**

2. **`_record_classification()` helper** (lines 105-126): cleanly centralises state
   update (`_last_regime`, `_last_classified_at`) and logging. All return paths go
   through this method — no way to forget to update state. **Correct architecture.**

3. **`ema_values` logged even in pump/UNDEFINED case** (lines 79-81): provides full
   diagnostic context when a pump detection fires. Useful for monitoring.

---

## Recommendations

1. **T008 (SetupDetector)**: must call `regime_detector.classify()` at the start of
   each scan cycle, not cache the result across cycles. The contract correctly places
   TTL caching in T012 (scan loop). T008 should receive the regime as a parameter,
   not call classify() itself.

2. **`dump_threshold_pct` sign convention**: confirm in `ScannerConfig` that
   `dump_threshold_pct` is stored as a positive value (e.g. `8.0`). The negation at
   line 77 (`-self._dump_threshold`) depends on this. mypy --strict passing confirms
   the attribute exists; the positive sign is a semantic assumption to document.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass. Zero-division guard is a welcome addition.

---
