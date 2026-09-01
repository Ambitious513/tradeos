# TASK_008_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Statistical)
# Task ID: T008
# Date: 2026-09-01

---

## Summary

Quantitative review of T008 SetupDetector. Focus: formula correctness for
all SHORT and LONG rules, directional sign conventions, 24H stats window,
stop wideness logic, and threshold inclusivity.

---

## Formula Verification

### compute_24h_stats (R-002)

| Check | Status | Detail |
|---|---|---|
| Window: last 24 closed candles | ✅ PASS | Line 48: `candles[-24:]` — correct |
| Reference: `candles[-25].close` | ✅ PASS | Line 45: 24H ago close at 1H resolution |
| high_24h = max(high) | ✅ PASS | Line 49: `max(candle.high for candle in window)` |
| low_24h = min(low) | ✅ PASS | Line 50: `min(candle.low for candle in window)` |
| change_pct formula | ✅ PASS | Line 51: `(close_now - ref) / ref * 100` — correct |
| Zero reference guard | ✅ PASS | Lines 46-47: `if reference_close == 0: return None` |
| Minimum candles: 25 | ✅ PASS | Line 43: `len(candles) < 25` |

**Note on window definition**: `candles[-24:]` gives the 24 most recent candles
(current + 23 prior). `candles[-25]` is 24 intervals ago. At 1H resolution:
24 candles back = 24H back. This is the correct interpretation. ✅

### EMA Extension (R-003 / compute_ema_extension)

| Direction | Formula | Status |
|---|---|---|
| SHORT | `(close - EMA7) / EMA7 * 100` | ✅ Correct — positive when close > EMA7 |
| LONG | `(EMA7 - close) / EMA7 * 100` | ✅ Correct — positive when close < EMA7 |

Both compared to `config.ema7_extension_pct` (3.0) with `>= 3.0`. ✅

### Threshold Inclusivity

| Condition | Code | Inclusive | Spec |
|---|---|---|---|
| SHORT pump | `change_24h_pct >= Decimal(str(config.pump_threshold_pct))` | ✅ `>=` | ✅ |
| SHORT RSI | `rsi_decimal >= Decimal(str(config.rsi_overbought))` | ✅ `>=` | ✅ |
| SHORT EMA ext | `extension_pct >= Decimal(str(config.ema7_extension_pct))` | ✅ `>=` | ✅ |
| LONG dump | `change_24h_pct <= -Decimal(str(config.dump_threshold_pct))` | ✅ `<=` | ✅ |
| LONG RSI | `rsi_decimal <= Decimal(str(config.rsi_oversold))` | ✅ `<=` | ✅ |
| LONG EMA ext | Same `>=` as SHORT | ✅ `>=` | ✅ |

**RSI comparison via Decimal**: `Decimal(str(rsi_14))` converts the float RSI to
Decimal for threshold comparison. This is the correct approach — avoids float
comparison with the Decimal threshold. ✅

### Stop Formulae

**SHORT-008**: `stop = MAX(structural_stop, atr_stop)`
- structural = `max(high for last 3 candles) + 0.1% × entry` → ABOVE entry ✅
- atr_stop = `entry + 1.5 × ATR14` → ABOVE entry ✅
- MAX picks the higher (wider from entry) stop ✅

**LONG-009**: `stop = MIN(structural_stop, atr_stop)`
- structural = `min(low for last 3 candles) - 0.1% × entry` → BELOW entry ✅
- atr_stop = `entry - 1.5 × ATR14` → BELOW entry ✅
- MIN picks the lower (wider from entry = further below entry) stop ✅

**Threshold verification**: Codex confirms structural 101.1 vs ATR 101.5 → 101.5 (SHORT ✅);
structural 98.9 vs ATR 98.5 → 98.5 (LONG ✅). Direction-correct.

### Take Profit (SHORT-009 / LONG-010)

| Direction | Formula | Status |
|---|---|---|
| SHORT | `entry - 2 × (stop - entry)` | ✅ Correct — TP below entry |
| LONG | `entry + 2 × (entry - stop)` | ✅ Correct — TP above entry |

### 24H Level Interaction (SHORT-004 / LONG-004)

SHORT: `proximity_pct = (high_24h - candle.high) / high_24h × 100 <= 0.5%`
- Positive when below 24H high; negative when above (also qualifies). ✅

LONG: `proximity_pct = (candle.low - low_24h) / low_24h × 100 <= 0.5%`
- Positive when above 24H low; negative when below (also qualifies). ✅

Both use `<= _LEVEL_PROXIMITY_PCT` (0.5) which is inclusive. ✅

### Retest Proximity

`abs(candle.high - rejection_close) / rejection_close × 100 <= 0.5%` (SHORT)

Uses `rejection_close` as denominator (not high_24h). Matches contract R-006. ✅

### Sweep Depth

`(low_24h - candle.low) / low_24h × 100 >= 0.1%`

Uses `low_24h` as denominator. Positive when candle.low < low_24h (swept below). ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All 16 functions are quantitatively correct. Every formula
matches STRATEGY_SPEC.md §4 and §5 exactly.

---
