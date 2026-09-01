# TASK_008_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T008
# Date: 2026-09-01

---

## Summary

Adversarial review of T008 SetupDetector. Focus: zero guards, doji edge cases,
index safety, Decimal leakage, and boundary arithmetic.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | EMA7 = 0 guard in `compute_ema_extension` | ✅ PASS | Line 112: `if ema_7 == 0: return None` — propagated to `detect_initial_conditions` line 72 |
| R-02 | `rejection_close == 0` guard in retests | ✅ PASS | Line 166 (`check_retest_short`) and line 180 (`check_retest_long`) |
| R-03 | `low_24h == 0` guard in sweep | ✅ PASS | Line 145 `check_liquidity_sweep` |
| R-04 | `level_24h == 0` guard in level interaction | ✅ PASS | Line 123 |
| R-05 | `risk == 0` guard in R:R check | ✅ PASS | Line 244: `if risk == 0: return False` |
| R-06 | Doji (body=0) rejection — bearish | ✅ PASS | Line 135: `if body <= 0: return False` — catches doji AND bullish candle together |
| R-07 | Doji (body=0) rejection — bullish | ✅ PASS | Line 154: `if body <= 0: return False` |
| R-08 | Fewer than 28 candles → None (warmup) | ✅ PASS | Line 62: `if len(candles) < 28: return None` |
| R-09 | `compute_24h_stats` with exactly 25 candles | ✅ PASS | `len < 25` fails; 25 candles → proceeds |
| R-10 | `recent_candles[-3:]` with < 3 candles | ✅ PASS | Python slice `[-3:]` on short list returns all available — correct defensive behavior |
| R-11 | Stop SHORT always above entry | ✅ PASS | Both `structural + buffer` and `entry + ATR` are > entry; MAX is > entry |
| R-12 | Stop LONG always below entry | ✅ PASS | Both `structural - buffer` and `entry - ATR` are < entry; MIN is < entry |
| R-13 | No float for price arithmetic | ✅ PASS | All `Decimal` operations; RSI converted via `Decimal(str(rsi_14))` before comparison |
| R-14 | `del direction` in `check_minimum_rr` | ✅ PASS | Line 241: deletes unused `direction` param to satisfy mypy strict. Clean. |
| R-15 | `compute_avg_volume` warmup: `< period` | ✅ PASS | Line 251; returns None not empty list |
| R-16 | `sum(..., start=Decimal(0))` for volume avg | ✅ PASS | Line 253-255: correct Decimal accumulation |
| R-17 | 172 total tests / 42 new | ✅ PASS | Zero regression |

---

## Critical Issues

**None.**

---

## Positive Findings

1. **Module-level Decimal constants** (lines 11-16): all threshold constants defined
   once as `Decimal("0.5")` etc. at the top of the file. No magic number literals
   scattered through the code. Maintainable.

2. **`del direction`** in `check_minimum_rr` (line 241): removes the unused parameter
   to satisfy mypy `--strict` while keeping the function signature stable for callers
   who pass direction (future use). Correct pattern.

3. **`check_rejection_candle` composes `check_24h_level_interaction`** (line 138-140):
   no duplication of 24H level logic — rejection candle calls the dedicated check
   function. Same for `check_bullish_rejection_candle` calling `check_liquidity_sweep`.

4. **`detect_initial_conditions` warmup check is conservative**: 28 candles required
   (spec: 2× period=14). RSI needs `period+1=15` closes. ATR needs same. EMA7 needs 7.
   Spec says warmup minimum is 28; code enforces 28. The RSI/ATR calls may internally
   return None for some subsets, but the outer `if ... is None` guard catches any
   failure regardless. Correct.

---

## Recommendations

1. **T009 note**: `compute_avg_volume` returns a `Decimal | None`. T009 must
   handle the `None` case (insufficient candle history for volume scoring).
   The score for volume should be 0 pts if avg_volume is None.

2. **T010 note**: `check_retest_short` proximity check uses `abs(candle.high -
   rejection_close)`. If a candle high overshoots significantly above rejection_close,
   this proximity check will fail (correctly). T010 should not assume retest succeeds
   on the first candle after rejection — it may take several candles.

---

## Release Recommendation

**APPROVED** — All edge cases handled correctly.

---
