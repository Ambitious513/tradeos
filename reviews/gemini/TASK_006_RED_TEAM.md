# TASK_006_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T006
# Date: 2026-09-01

---

## Summary

Adversarial review of T006 Technical Indicators. Focus areas: edge cases,
input mutation, Decimal vs float leakage, and formula boundary conditions.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Input list not mutated | ✅ PASS | No `.sort()`, `.reverse()`, or in-place operation on input; `zip` + slicing are read-only |
| R-02 | `period=1` EMA | ✅ PASS | `len(candles) < 1` is False for any non-empty list; seed = close[0]/1 = close[0]; no update loop runs; returns last close correctly |
| R-03 | `period=1` RSI | ✅ PASS | Requires `len >= 2`; changes = [c1-c0]; seed = gains[0]/1 = gain; no update loop; returns valid RSI |
| R-04 | All-same prices → RSI 50.0 | ✅ PASS | All changes = 0; avg_gain = avg_loss = 0; line 31-32 returns 50.0 |
| R-05 | All-rising prices → RSI 100.0 | ✅ PASS | avg_loss = 0; avg_gain > 0; line 33-34 returns 100.0 |
| R-06 | All-falling prices → RSI 0.0 | ✅ PASS | avg_gain = 0; avg_loss > 0; lines 35-36 returns 0.0 |
| R-07 | ATR gap-up (prev_close > current high) | ✅ PASS | `abs(current.high - previous.close)` and `abs(current.low - previous.close)` both computed; `max()` picks the gap component |
| R-08 | ATR gap-down (prev_close < current low) | ✅ PASS | Same as above — `abs(current.low - previous.close)` captures downward gap |
| R-09 | `period < 1` → `ValueError` | ✅ PASS | `_validate_period()` called first in all three functions |
| R-10 | `period = 0` → `ValueError` | ✅ PASS | `0 < 1` → raises |
| R-11 | Empty candles → `None` (not raises) | ✅ PASS | Line 14: `if not candles` before any indexing |
| R-12 | No float leakage in EMA | ✅ PASS | `Decimal(2)`, `Decimal(period + 1)`, `Decimal(1)` — all explicit; no `float()` call |
| R-13 | No float leakage in ATR | ✅ PASS | `Decimal(period)`, `Decimal(period-1)` — all explicit |
| R-14 | RSI internal uses Decimal | ✅ PASS | `gains`/`losses` are `list[Decimal]`; only `float()` at the final return |
| R-15 | 111 total tests / 100% indicator coverage | ✅ PASS | Zero regression |
| R-16 | `zip(..., strict=True)` in RSI | ✅ PASS | Line 27: `strict=True` ensures `gains[period:]` and `losses[period:]` always same length — they will be, as they're both slices of the same-length `changes` list |

---

## Critical Issues

**None.**

---

## Positive Findings (beyond spec)

1. **`zip(..., strict=True)`** in `rsi.py` line 27: detects any accidental mismatch
   between `gains[period:]` and `losses[period:]` at runtime. Because both are slices
   of `changes` (same length), this will never trigger in practice — but it's a correct
   defensive check that would catch a future refactor error. **Retained.**

2. **`_validate_period()` extracted as a private function** in each module: consistent
   enforcement across all three indicators. If the validation logic ever needs to change
   (e.g., add a maximum period), there's one place per module to update.

3. **`sum(..., start=Decimal(0))`**: avoids the `int + Decimal` implicit conversion
   trap that the built-in `sum()` would hit without a `start` argument.

---

## Recommendations

1. **T007**: The `ema()` function is called 4 times with the same `candles` list (EMA7,
   EMA14, EMA28, EMA200). Each call re-iterates the full list from scratch. For 200+
   candles this is trivial (< 1ms total), but if the regime is evaluated on a tight loop,
   consider a future multi-EMA batch function. **Not a blocking concern for T007.**

2. **Backtest engine (T014)**: Confirm that the backtest candle feed delivers candles
   in strictly ascending `open_time` order before these functions are called. The
   functions do not sort — they trust the caller.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass. Implementation is tight, correct, and defensive.

---
